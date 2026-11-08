//! Blocking calls to the Hive HTTP API. They wait on the network, so run them off the UI thread
//! (see `bg`).

use std::io::{BufRead, BufReader};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use anyhow::{Result, bail};
use gpui_kit::{App, Global};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Clone)]
pub struct Api {
    base: String,
    agent: ureq::Agent,
    // An event stream stays open for as long as its view does, so it can't share the request timeout.
    stream_agent: ureq::Agent,
}

/// The app's one connection to the server.
pub struct HiveApi(pub Api);

impl Global for HiveApi {}

pub fn api(cx: &App) -> Api {
    cx.global::<HiveApi>().0.clone()
}

#[derive(Clone, Debug, Deserialize)]
pub struct Queen {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub has_avatar: bool,
    /// What her drawn portrait looks like, for when she has no picture.
    #[serde(default)]
    pub portrait: Option<Value>,
}

/// One past or present conversation, as `GET /api/sessions/history` lists it.
#[derive(Clone, Debug, Deserialize)]
pub struct SessionSummary {
    pub session_id: String,
    #[serde(default)]
    pub queen_id: Option<String>,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub last_message: Option<String>,
    #[serde(default)]
    pub message_count: Option<i64>,
    #[serde(default)]
    pub last_active_at: Option<f64>,
    #[serde(default)]
    pub created_at: Option<f64>,
    #[serde(default)]
    pub live: bool,
    /// Where a colony session's agent lives; its last segment is the colony's name.
    #[serde(default)]
    pub agent_path: Option<String>,
}

/// One page of a session's recorded events, oldest first.
pub struct HistoryPage {
    pub events: Vec<Value>,
    /// Where to continue for older events, if there are any.
    pub older: Option<HistoryCursor>,
}

#[derive(Clone, Copy, Debug)]
pub struct HistoryCursor {
    offset: i64,
    index: i64,
}

/// A file to send with [`Api::post_multipart`].
pub struct FilePart {
    pub field: String,
    pub filename: String,
    pub content_type: String,
    pub bytes: Vec<u8>,
}

/// How an event stream ended.
pub enum StreamEnd {
    /// The server closed it; reconnect.
    Closed,
    /// The session isn't running (404); resume it before reconnecting.
    NotLive,
    /// The caller asked to stop.
    Stopped,
}

fn agent(timeout: Option<Duration>) -> ureq::Agent {
    ureq::Agent::config_builder()
        .http_status_as_error(false)
        // The server is on this machine; a proxy from the environment would only get in the way.
        .proxy(None)
        .timeout_global(timeout)
        .build()
        .into()
}

impl Api {
    pub fn new(base: &str) -> Self {
        Self {
            base: base.trim_end_matches('/').to_string(),
            agent: agent(Some(Duration::from_secs(60))),
            stream_agent: agent(None),
        }
    }

    pub fn base(&self) -> &str {
        &self.base
    }

    pub fn url(&self, path: &str) -> String {
        format!("{}/api{}", self.base, path)
    }

    fn read(mut resp: ureq::http::Response<ureq::Body>) -> Result<Value> {
        let status = resp.status().as_u16();
        // History pages carry whole tool results, well past ureq's 10 MB default.
        let text = resp.body_mut().with_config().limit(256 * 1024 * 1024).read_to_string()?;
        let body: Value =
            if text.is_empty() { Value::Null } else { serde_json::from_str(&text).unwrap_or(Value::String(text)) };
        if status >= 400 {
            bail!("HTTP {status}: {}", error_reason(&body));
        }
        Ok(body)
    }

    pub fn get(&self, path: &str) -> Result<Value> {
        Self::read(self.agent.get(&self.url(path)).call()?)
    }

    pub fn post(&self, path: &str, body: Value) -> Result<Value> {
        Self::read(self.agent.post(&self.url(path)).send_json(body)?)
    }

    pub fn put(&self, path: &str, body: Value) -> Result<Value> {
        Self::read(self.agent.put(&self.url(path)).send_json(body)?)
    }

    pub fn patch(&self, path: &str, body: Value) -> Result<Value> {
        Self::read(self.agent.patch(&self.url(path)).send_json(body)?)
    }

    pub fn delete(&self, path: &str) -> Result<Value> {
        Self::read(self.agent.delete(&self.url(path)).call()?)
    }

    /// A `multipart/form-data` POST: text `fields`, plus an optional file.
    pub fn post_multipart(&self, path: &str, fields: &[(&str, &str)], file: Option<FilePart>) -> Result<Value> {
        let nanos =
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
        let boundary = format!("----hive-desktop-{nanos:x}");
        let mut body = Vec::new();
        for (name, value) in fields {
            body.extend_from_slice(
                format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n")
                    .as_bytes(),
            );
        }
        if let Some(file) = file {
            let filename = file.filename.replace('"', "");
            body.extend_from_slice(
                format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{}\"; filename=\"{filename}\"\r\nContent-Type: {}\r\n\r\n", file.field, file.content_type).as_bytes(),
            );
            body.extend_from_slice(&file.bytes);
            body.extend_from_slice(b"\r\n");
        }
        body.extend_from_slice(format!("--{boundary}--\r\n").as_bytes());
        let resp = self
            .agent
            .post(&self.url(path))
            .header("Content-Type", format!("multipart/form-data; boundary={boundary}"))
            .send(&body[..])?;
        Self::read(resp)
    }

    /// Raw bytes, e.g. an avatar image.
    pub fn bytes(&self, path: &str) -> Result<Vec<u8>> {
        let mut resp = self.agent.get(&self.url(path)).call()?;
        let status = resp.status().as_u16();
        if status >= 400 {
            bail!("HTTP {status} for {path}");
        }
        Ok(resp.body_mut().with_config().limit(64 * 1024 * 1024).read_to_vec()?)
    }

    pub fn queens(&self) -> Result<Vec<Queen>> {
        let body = self.get("/queen/profiles")?;
        Ok(serde_json::from_value(body["queens"].clone())?)
    }

    pub fn sessions(&self) -> Result<Vec<SessionSummary>> {
        let body = self.get("/sessions/history")?;
        Ok(serde_json::from_value(body["sessions"].clone())?)
    }

    /// The queen's running direct chat, else her newest one on disk, else a new one.
    pub fn open_session(&self, queen_id: &str) -> Result<String> {
        let body = self.post(&format!("/queen/{queen_id}/session"), json!({ "initial_phase": "independent" }))?;
        session_id_of(&body, queen_id)
    }

    /// Reopen one of the queen's past chats. `Err` names the colony when the session belongs to one.
    pub fn select_session(&self, queen_id: &str, session_id: &str) -> Result<String> {
        let body = self.post(&format!("/queen/{queen_id}/session/select"), json!({ "session_id": session_id }))?;
        if body["status"] == "colony" {
            bail!("that conversation now lives in colony {}", body["colony_id"].as_str().unwrap_or("?"));
        }
        // Forks are followed forward, so the id that comes back can differ from the one asked for.
        session_id_of(&body, queen_id).or_else(|_| Ok(session_id.to_string()))
    }

    /// Start a fresh chat with the queen. The server stops her other direct chats, as the web's "New chat" does.
    pub fn new_session(&self, queen_id: &str) -> Result<String> {
        let body = self.post(&format!("/queen/{queen_id}/session/new"), json!({ "initial_phase": "independent" }))?;
        session_id_of(&body, queen_id)
    }

    /// The newest `limit` events, or the `limit` before `cursor`.
    pub fn history(&self, session_id: &str, limit: usize, cursor: Option<HistoryCursor>) -> Result<HistoryPage> {
        let mut path = format!("/sessions/{session_id}/events/history?limit={limit}");
        if let Some(c) = cursor {
            path.push_str(&format!("&before_offset={}&before_index={}", c.offset, c.index));
        }
        let body = self.get(&path)?;
        let older =
            match (body["has_more_older"].as_bool(), body["start_offset"].as_i64(), body["start_index"].as_i64()) {
                (Some(true), Some(offset), Some(index)) => Some(HistoryCursor { offset, index }),
                _ => None,
            };
        Ok(HistoryPage { events: body["events"].as_array().cloned().unwrap_or_default(), older })
    }

    pub fn send(&self, session_id: &str, message: &str) -> Result<()> {
        self.post(&format!("/sessions/{session_id}/chat"), json!({ "message": message }))?;
        Ok(())
    }

    /// Send with attachments: `images` are `image_url` parts (data URIs, or `hive-attachment://`
    /// paths from [`Self::upload_attachment`]); `display` is what the user's bubble shows.
    pub fn send_with(
        &self,
        session_id: &str,
        message: &str,
        images: Vec<Value>,
        display: Option<String>,
    ) -> Result<()> {
        let mut body = json!({ "message": message, "images": images });
        if let Some(display) = display {
            body["display_message"] = json!(display);
        }
        self.post(&format!("/sessions/{session_id}/chat"), body)?;
        Ok(())
    }

    /// Put a non-image file in the session's attachments; returns its `hive-attachment://` URL.
    pub fn upload_attachment(&self, session_id: &str, file: FilePart) -> Result<String> {
        let body = self.post_multipart(&format!("/sessions/{session_id}/upload-attachment"), &[], Some(file))?;
        match body["filename"].as_str() {
            Some(name) => Ok(format!("hive-attachment://data/attachments/{name}")),
            None => bail!("the server kept no file: {body}"),
        }
    }

    /// The colony's own session, started or resumed; the server picks which.
    pub fn open_colony(&self, colony: &str) -> Result<Value> {
        let body = self.post("/sessions", json!({ "colony_id": colony }))?;
        if body["session_id"].as_str().is_none() {
            bail!("the server opened no session for colony {colony}: {body}");
        }
        Ok(body)
    }

    /// Bring a stopped colony session back so its stream can be opened again.
    pub fn resume_colony(&self, session_id: &str, colony: &str) -> Result<()> {
        self.post("/sessions", json!({ "colony_id": colony, "queen_resume_from": session_id }))?;
        Ok(())
    }

    pub fn cancel(&self, session_id: &str) -> Result<()> {
        let body = self.post(&format!("/sessions/{session_id}/cancel-queen"), json!({}))?;
        if body["cancelled"] == Value::Bool(false) {
            bail!("{}", body["error"].as_str().unwrap_or("the queen wasn't running"));
        }
        Ok(())
    }

    /// Bring a stopped session back so its stream can be opened again.
    pub fn resume(&self, session_id: &str, queen_id: &str) -> Result<()> {
        self.post("/sessions", json!({ "queen_resume_from": session_id, "queen_name": queen_id }))?;
        Ok(())
    }

    /// Read a server-sent event stream at `path`, handing each frame's JSON to `on_event` until it
    /// returns false or `stop` is set. `stop` is checked on every line, so keepalives bound how
    /// long stopping takes. Named frames (`event: x`) arrive as `{"event": x, "data": ...}`.
    pub fn stream(&self, path: &str, stop: &AtomicBool, mut on_event: impl FnMut(Value) -> bool) -> Result<StreamEnd> {
        let resp = self.stream_agent.get(&self.url(path)).header("Accept", "text/event-stream").call()?;
        match resp.status().as_u16() {
            404 => return Ok(StreamEnd::NotLive),
            status if status >= 400 => bail!("HTTP {status} opening {path}"),
            _ => {}
        }
        let reader = BufReader::new(resp.into_body().into_reader());
        let mut name = String::new();
        let mut data = String::new();
        for line in reader.lines() {
            let line = line?;
            if stop.load(Ordering::Relaxed) {
                return Ok(StreamEnd::Stopped);
            }
            if let Some(rest) = line.strip_prefix("data:") {
                if !data.is_empty() {
                    data.push('\n');
                }
                data.push_str(rest.strip_prefix(' ').unwrap_or(rest));
            } else if let Some(rest) = line.strip_prefix("event:") {
                name = rest.trim().to_string();
            } else if line.is_empty() && !data.is_empty() {
                let parsed = serde_json::from_str::<Value>(&data);
                data.clear();
                let event_name = std::mem::take(&mut name);
                // A frame that isn't JSON is the server's business, not a reason to drop the view.
                if let Ok(parsed) = parsed {
                    let event =
                        if event_name.is_empty() { parsed } else { json!({ "event": event_name, "data": parsed }) };
                    if !on_event(event) {
                        return Ok(StreamEnd::Stopped);
                    }
                }
            }
            // `: keepalive` comments and `id:` lines carry nothing the app reads.
        }
        Ok(StreamEnd::Closed)
    }
}

/// What an error body says: its `error` (or `detail`), plus the `unknown` names a rejected tool
/// list carries and the `fix` an MCP failure suggests.
pub fn error_reason(body: &Value) -> String {
    let mut reason = body
        .get("error")
        .or_else(|| body.get("detail"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| body.to_string());
    if let Some(unknown) = body["unknown"].as_array().filter(|u| !u.is_empty()) {
        let names: Vec<&str> = unknown.iter().filter_map(Value::as_str).collect();
        reason.push_str(&format!(": {}", names.join(", ")));
    }
    if let Some(fix) = body["fix"].as_str().filter(|f| !f.is_empty()) {
        reason.push_str(&format!(". {fix}"));
    }
    reason
}

/// Standard base64 with padding, for `data:` URIs.
pub fn base64(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let n = chunk.iter().enumerate().fold(0u32, |n, (i, &b)| n | (b as u32) << (16 - 8 * i));
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(ALPHABET[(n >> (18 - 6 * i) & 63) as usize] as char);
            } else {
                out.push('=');
            }
        }
    }
    out
}

/// Percent-encode text for a URL query value or path segment (RFC 3986 unreserved characters pass).
pub fn encode(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for byte in text.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => out.push(byte as char),
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

fn session_id_of(body: &Value, queen_id: &str) -> Result<String> {
    match body["session_id"].as_str() {
        Some(id) => Ok(id.to_string()),
        None => bail!("the server opened no session for {queen_id}: {body}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64_matches_rfc_4648_vectors() {
        let cases =
            [("", ""), ("f", "Zg=="), ("fo", "Zm8="), ("foo", "Zm9v"), ("foob", "Zm9vYg=="), ("foobar", "Zm9vYmFy")];
        for (plain, encoded) in cases {
            assert_eq!(base64(plain.as_bytes()), encoded);
        }
    }

    #[test]
    fn error_reason_adds_unknown_names_and_the_fix() {
        assert_eq!(
            error_reason(&json!({"error": "Unknown MCP tool name(s)", "unknown": ["ava_x", "zed_y"]})),
            "Unknown MCP tool name(s): ava_x, zed_y"
        );
        assert_eq!(
            error_reason(&json!({"error": "Command not found", "fix": "Install it first"})),
            "Command not found. Install it first"
        );
        assert_eq!(error_reason(&json!({"detail": "Not allowed"})), "Not allowed");
    }

    #[test]
    fn encode_leaves_unreserved_characters_and_escapes_the_rest() {
        assert_eq!(encode("queens/ava memory.md"), "queens%2Fava%20memory.md");
        assert_eq!(encode("é"), "%C3%A9");
    }
}
