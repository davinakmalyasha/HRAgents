use crate::time::BusinessDate;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct PolicyDocument {
    pub slug: String,
    pub title: String,
    pub body: String,
    pub effective_from: Option<BusinessDate>,
    pub owner: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, schemars::JsonSchema)]
pub struct PolicyHit {
    pub slug: String,
    pub title: String,
    pub excerpt: String,
    pub score: u32,
}

#[derive(Debug, Clone, Default)]
pub struct PolicyCorpus {
    documents: Vec<PolicyDocument>,
}

impl PolicyCorpus {
    pub fn new(documents: Vec<PolicyDocument>) -> Self {
        Self { documents }
    }

    pub fn add(&mut self, document: PolicyDocument) {
        self.documents.push(document);
    }

    pub fn documents(&self) -> &[PolicyDocument] {
        &self.documents
    }

    /// Deterministic keyword retrieval. Ask HR may use embeddings as an
    /// additional recall path, but the cited source and the ranking fallback
    /// must work without a model and without a network.
    pub fn search(&self, query: &str, limit: usize) -> Vec<PolicyHit> {
        let terms = tokenize(query);
        if terms.is_empty() || limit == 0 {
            return Vec::new();
        }
        let mut hits: Vec<PolicyHit> = self
            .documents
            .iter()
            .filter_map(|document| {
                let haystack = format!("{} {}", document.title, document.body).to_lowercase();
                let title = document.title.to_lowercase();
                let mut score = 0_u32;
                for term in &terms {
                    if title.contains(term) {
                        score += 5;
                    }
                    if haystack.contains(term) {
                        score += 1;
                    }
                }
                if score == 0 {
                    return None;
                }
                let excerpt = best_excerpt(&document.body, &terms);
                Some(PolicyHit {
                    slug: document.slug.clone(),
                    title: document.title.clone(),
                    excerpt,
                    score,
                })
            })
            .collect();
        hits.sort_by(|a, b| b.score.cmp(&a.score).then_with(|| a.slug.cmp(&b.slug)));
        hits.truncate(limit);
        hits
    }
}

fn tokenize(query: &str) -> BTreeSet<String> {
    query
        .to_lowercase()
        .split(|ch: char| !ch.is_alphanumeric())
        .filter(|term| term.len() >= 3)
        .filter(|term| !STOP_WORDS.contains(term))
        .map(str::to_owned)
        .collect()
}

fn best_excerpt(body: &str, terms: &BTreeSet<String>) -> String {
    let lower = body.to_lowercase();
    let mut best = 0_usize;
    let mut best_score = 0_usize;
    for (index, _) in lower.char_indices() {
        let window = &lower[index..lower.len().min(index + 240)];
        let score = terms
            .iter()
            .filter(|term| window.contains(term.as_str()))
            .count();
        if score > best_score {
            best_score = score;
            best = index;
        }
    }
    let start = best.saturating_sub(40);
    let end = lower.len().min(start + 240);
    let mut excerpt = body[start..end].trim().to_owned();
    if start > 0 {
        excerpt.insert(0, '…');
    }
    if end < body.len() {
        excerpt.push('…');
    }
    excerpt
}

const STOP_WORDS: &[&str] = &[
    "the", "and", "for", "how", "what", "when", "who", "why", "does", "with", "from", "that",
    "this", "are", "can", "you", "our", "have", "many", "much", "days", "day",
];

#[cfg(test)]
mod tests {
    use super::*;

    fn corpus() -> PolicyCorpus {
        PolicyCorpus::new(vec![
            PolicyDocument {
                slug: "leave".into(),
                title: "Annual leave policy".into(),
                body: "Employees receive 12 days of annual leave per year. Unused leave may be carried over up to 3 days.".into(),
                effective_from: None,
                owner: Some("HR".into()),
            },
            PolicyDocument {
                slug: "expense".into(),
                title: "Expense policy".into(),
                body: "Submit receipts within 14 days. Travel requires manager approval.".into(),
                effective_from: None,
                owner: Some("Finance".into()),
            },
        ])
    }

    #[test]
    fn retrieval_is_cited_and_deterministic() {
        let corpus = corpus();
        let hits = corpus.search("how many annual leave days carry over", 3);
        assert_eq!(hits[0].slug, "leave");
        assert!(hits[0].excerpt.to_lowercase().contains("leave"));
        assert_eq!(
            hits,
            corpus.search("how many annual leave days carry over", 3)
        );
    }

    #[test]
    fn no_match_returns_empty() {
        assert!(corpus().search("quantum entanglement", 3).is_empty());
    }
}
