//! Recorded provider replay: no network, three distinct extraction runs.
//!
//! The fixture is a captured OpenAI-compatible response sequence. CI runs this
//! test with the rest of the workspace; the live provider test stays ignored.

use hragents_agents::provider::{ProviderExtractor, ReplayLlmClient};
use hragents_core::hiring::{Dimension, Evaluation, Rubric};
use hragents_core::ids::ApplicationId;
use hragents_core::time::UtcInstant;
use serde::Deserialize;
use std::collections::BTreeMap;

#[derive(Deserialize)]
struct Fixture {
    document: String,
    responses: Vec<String>,
    expected: Expected,
}

#[derive(Deserialize)]
struct Expected {
    runs: usize,
    dimension_scores_bp: BTreeMap<String, i64>,
    overall_bp: i64,
    evidence_count: usize,
}

#[test]
fn recorded_provider_replay_matches_expected() {
    let fixture: Fixture = serde_json::from_str(include_str!("fixtures/provider_replay.json"))
        .expect("replay fixture is valid JSON");

    let client = ReplayLlmClient::new().with_sequence(fixture.responses.clone());
    let extractor = ProviderExtractor::new(client).with_runs(3);
    let dimensions = vec![
        Dimension {
            key: "technical_depth".into(),
            label: "Technical depth".into(),
            weight_bp: 4_000,
        },
        Dimension {
            key: "stack_alignment".into(),
            label: "Stack alignment".into(),
            weight_bp: 3_000,
        },
        Dimension {
            key: "systems_literacy".into(),
            label: "Systems literacy".into(),
            weight_bp: 2_000,
        },
        Dimension {
            key: "verifiable_certifications".into(),
            label: "Verifiable certifications".into(),
            weight_bp: 1_000,
        },
    ];
    let result = extractor
        .extract_structured(&fixture.document, None, &dimensions)
        .expect("recorded responses parse and validate");
    assert_eq!(result.runs.len(), fixture.expected.runs);
    assert_eq!(result.evidence.len(), fixture.expected.evidence_count);
    // The fence on the second response must not survive parsing.
    assert!(
        result
            .runs
            .iter()
            .all(|run| run.dimension_scores.len() == 4)
    );

    let rubric = Rubric {
        id: "provider-replay-v1".into(),
        name: "Provider replay".into(),
        dimensions,
        merit_floor_bp: 7_000,
        sigma_limit_bp: 500,
    };
    let evaluation = Evaluation::from_runs(
        ApplicationId::new(),
        &rubric,
        &result.runs,
        result.evidence,
        UtcInstant::from_millis(1_760_000_000_000).unwrap(),
    )
    .expect("merged provider runs are valid");
    assert_eq!(
        evaluation.dimension_scores,
        fixture.expected.dimension_scores_bp
    );
    assert_eq!(evaluation.overall_bp, fixture.expected.overall_bp);
    assert!(evaluation.sigma_bp > 0, "three distinct runs must vary");
    assert!(
        !evaluation
            .flags
            .iter()
            .any(|flag| flag == "inconsistent_extraction")
    );
}
