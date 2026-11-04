//! Document text extraction for CVs and attachments.
//!
//! Plain text passes through; PDFs go through `pdf-extract`; `.docx` files are
//! traversed paragraph-by-paragraph (tables included). Anything else is
//! rejected with the list of supported types — never silently skipped.

use super::AgentError;

const MAX_BYTES: usize = 25 * 1024 * 1024;
const MAX_CHARS: usize = 200_000;

/// Extract plain text from an uploaded file. `filename` decides the parser;
/// the bytes are never executed, only read.
pub fn extract_text(filename: &str, bytes: &[u8]) -> Result<String, AgentError> {
    if bytes.is_empty() {
        return Err(AgentError::EmptyDocument);
    }
    if bytes.len() > MAX_BYTES {
        return Err(AgentError::Unreadable(format!(
            "file is {} bytes; documents are limited to 25 MB",
            bytes.len()
        )));
    }
    let extension = filename
        .rsplit('.')
        .next()
        .map(str::to_lowercase)
        .unwrap_or_default();
    let text = match extension.as_str() {
        "txt" | "md" | "markdown" | "csv" | "text" => String::from_utf8(bytes.to_vec())
            .map_err(|_| AgentError::Unreadable("file is not valid UTF-8 text".into()))?,
        "pdf" => pdf_extract::extract_text_from_mem(bytes)
            .map_err(|error| AgentError::Unreadable(format!("PDF parse failed: {error}")))?,
        "docx" => extract_docx(bytes)?,
        other => return Err(AgentError::UnsupportedType(other.into())),
    };
    let text = normalize(&text);
    if text.trim().is_empty() {
        return Err(AgentError::EmptyDocument);
    }
    Ok(text)
}

fn extract_docx(bytes: &[u8]) -> Result<String, AgentError> {
    use quick_xml::events::Event;
    use std::io::{Cursor, Read};

    let mut archive = zip::ZipArchive::new(Cursor::new(bytes))
        .map_err(|error| AgentError::Unreadable(format!("DOCX zip failed: {error}")))?;
    let mut xml = String::new();
    archive
        .by_name("word/document.xml")
        .map_err(|_| AgentError::Unreadable("DOCX has no word/document.xml".into()))?
        .read_to_string(&mut xml)
        .map_err(|error| AgentError::Unreadable(format!("DOCX read failed: {error}")))?;
    let mut reader = quick_xml::Reader::from_str(&xml);
    reader.config_mut().trim_text(true);
    let mut parts: Vec<String> = Vec::new();
    let mut current = String::new();
    let flush = |current: &mut String, parts: &mut Vec<String>| {
        let line = current.trim().to_owned();
        if !line.is_empty() {
            parts.push(line);
        }
        current.clear();
    };
    loop {
        match reader.read_event() {
            Ok(Event::Start(element)) => match element.name().as_ref() {
                "w:p" | "w:tr" => flush(&mut current, &mut parts),
                "w:tab" => current.push(' '),
                _ => {}
            },
            Ok(Event::Empty(element)) => match element.name().as_ref() {
                "w:br" | "w:tab" => current.push(' '),
                _ => {}
            },
            Ok(Event::Text(text)) => {
                current.push_str(&text.xml10_content());
            }
            Ok(Event::End(element)) => {
                if element.name().as_ref() == "w:p" || element.name().as_ref() == "w:tr" {
                    flush(&mut current, &mut parts);
                }
            }
            Ok(Event::Eof) => break,
            Err(error) => {
                return Err(AgentError::Unreadable(format!("DOCX XML failed: {error}")));
            }
            _ => {}
        }
    }
    flush(&mut current, &mut parts);
    Ok(parts.join("\n"))
}

fn normalize(text: &str) -> String {
    let mut out = String::with_capacity(text.len().min(MAX_CHARS + 1));
    let mut blanks = 0;
    for line in text.lines() {
        let trimmed = line.trim_end();
        if trimmed.trim().is_empty() {
            blanks += 1;
            if blanks <= 1 {
                out.push('\n');
            }
            continue;
        }
        blanks = 0;
        out.push_str(trimmed);
        out.push('\n');
    }
    if out.len() > MAX_CHARS {
        out.truncate(MAX_CHARS);
        out.push('…');
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_text_passes_through() {
        let text = extract_text("cv.txt", b"Built things.\n\nShipped them.").unwrap();
        assert!(text.contains("Built things."));
    }

    #[test]
    fn unsupported_type_names_itself() {
        assert!(matches!(
            extract_text("photo.png", b"not a png"),
            Err(AgentError::UnsupportedType(_))
        ));
    }

    #[test]
    fn empty_file_is_rejected() {
        assert!(matches!(
            extract_text("cv.txt", b""),
            Err(AgentError::EmptyDocument)
        ));
    }

    #[test]
    fn whitespace_only_is_rejected() {
        assert!(matches!(
            extract_text("cv.txt", b"   \n  \n"),
            Err(AgentError::EmptyDocument)
        ));
    }

    #[test]
    fn pdf_fixture_extracts() {
        let bytes = include_bytes!("../tests/fixtures/cv_sample.pdf");
        let text = extract_text("cv.pdf", bytes).unwrap();
        assert!(text.contains("Rust"), "pdf text was: {text:?}");
    }

    #[test]
    fn docx_fixture_extracts() {
        let bytes = include_bytes!("../tests/fixtures/cv_sample.docx");
        let text = extract_text("cv.docx", bytes).unwrap();
        assert!(text.contains("Rust"), "docx text was: {text:?}");
        assert!(text.contains("latency"), "docx text was: {text:?}");
    }
}
