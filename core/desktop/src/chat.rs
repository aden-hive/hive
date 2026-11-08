//! Replays a queen session's events into chat items, as the web chat does (`replayEvent` in
//! `frontend/src/lib/chat-helpers.ts`). History and the live stream send the same events, and the
//! stream replays some the history already had, so applying an event twice must change nothing.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

use serde_json::Value;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum ToolState {
    Running,
    Done,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Kind {
    User,
    Queen,
    Thinking,
    Tool {
        name: String,
        state: ToolState,
    },
    /// What the queen asked with `ask_user`.
    Question,
    /// Where a colony worker's run shows; its details come from the workers list, not events.
    Worker {
        id: String,
    },
    /// Errors, pauses and fired schedules.
    Notice,
}

#[derive(Clone, Debug)]
pub struct Item {
    pub id: String,
    pub kind: Kind,
    pub text: String,
    pub detail: Detail,
    /// When its first event came, as the server stamps it (local time, no zone); empty for notes
    /// the app made itself.
    pub at: String,
}

impl Item {
    /// "15:23", from [`Item::at`].
    pub fn time(&self) -> &str {
        self.at.get(11..16).unwrap_or("")
    }
}

/// What a tool call was given and gave back, shown when the call is opened; a user message's images.
#[derive(Clone, Debug, Default)]
pub struct Detail {
    pub input: Option<String>,
    pub result: Option<String>,
    /// Session-relative paths such as `data/attachments/x.png`.
    pub images: Vec<String>,
}

/// One `ask_user` question still waiting for an answer.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Question {
    pub id: String,
    pub prompt: String,
    /// Empty for a free-text question.
    pub options: Vec<String>,
}

fn questions_of(value: Option<&Value>) -> Vec<Question> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .enumerate()
        .map(|(ix, q)| Question {
            id: Some(str_of(q, "id"))
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .unwrap_or_else(|| format!("q{}", ix + 1)),
            // The server accepts `question` as another name for `prompt`.
            prompt: Some(str_of(q, "prompt")).filter(|s| !s.is_empty()).unwrap_or(str_of(q, "question")).to_string(),
            options: q
                .get("options")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect(),
        })
        .collect()
}

/// A user message without the `<system-reminder>` notes the server appends (e.g. where
/// attachments were saved); the web chat drops them too.
fn strip_reminders(text: &str) -> String {
    const OPEN: &str = "<system-reminder>";
    const CLOSE: &str = "</system-reminder>";
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(start) = rest.find(OPEN) {
        out.push_str(&rest[..start]);
        rest = match rest[start..].find(CLOSE) {
            Some(end) => &rest[start + end + CLOSE.len()..],
            None => "",
        };
    }
    out.push_str(rest);
    out.trim().to_string()
}

/// The text `/chat` takes as the answer: the bare answer for one question, else a
/// `"prompt"="answer"` line per question, as `queen-dm.tsx` sends it.
pub fn answer_text(questions: &[Question], answers: &[String]) -> String {
    if let ([_], [answer]) = (questions, answers) {
        return answer.clone();
    }
    questions.iter().zip(answers).map(|(q, a)| format!("\"{}\"=\"{}\"", q.prompt, a)).collect::<Vec<_>>().join("\n")
}

/// JSON as people read it; strings stay as they are rather than gaining quotes.
fn readable(value: &Value) -> Option<String> {
    match value {
        Value::Null => None,
        Value::String(s) => Some(s.clone()),
        other => serde_json::to_string_pretty(other).ok(),
    }
}

/// Something the caller has to act on, beyond redrawing.
#[derive(Debug, PartialEq, Eq)]
pub enum Signal {
    /// The session continues under a new id; follow it.
    Forked(String),
    /// The session's title changed.
    Title(String),
    /// The queen asked for a credential through a form (`client_credential_form_requested`).
    CredentialForm(Value),
    /// A skill install request was made or decided; re-read the pending list.
    SkillInstalls,
    /// The queen suggested starting a colony (`colony_suggestion_requested`).
    ColonySuggestion(Value),
    /// The task list changed.
    Tasks,
    /// A schedule was added, changed, fired or removed.
    Triggers,
    /// A colony worker started, reported or finished.
    Workers,
}

#[derive(Default)]
pub struct Chat {
    pub items: Vec<Item>,
    /// True while the queen is thinking or running a tool.
    pub busy: bool,
    /// The queen's unanswered `ask_user` questions; the composer becomes their answer form.
    pub pending: Vec<Question>,
    /// How full her context is, 0–100, from the last `context_usage_updated`.
    pub context_pct: Option<f64>,
    /// The timestamp of the event being applied, for the items it creates.
    now: String,
    index: HashMap<String, usize>,
    /// A bubble's text by inner turn; each delta carries its inner turn's whole text so far.
    parts: HashMap<String, BTreeMap<i64, String>>,
    /// Thinking bubbles whose final text has arrived; later deltas mustn't shorten them.
    settled: HashSet<String>,
    seen: HashSet<String>,
    /// When each user message arrived. A reply's bubble is keyed by the latest one before it, so a
    /// turn after a restart (when iterations count from 0 again) can't land in an earlier turn's
    /// bubble, and the key doesn't depend on the order events are applied in (a re-sent stream, or
    /// older history loaded later).
    inputs: BTreeSet<String>,
    /// The last snapshot's (seq, timestamp). Events the stream replays from before it already
    /// shaped that snapshot, so they draw bubbles but don't change `busy`.
    snapshot: Option<(i64, String)>,
}

fn str_of<'a>(v: &'a Value, key: &str) -> &'a str {
    v.get(key).and_then(Value::as_str).unwrap_or("")
}

fn int_of(v: &Value, key: &str) -> i64 {
    v.get(key).and_then(Value::as_i64).unwrap_or(0)
}

impl Chat {
    pub fn apply_all<'a>(&mut self, events: impl IntoIterator<Item = &'a Value>) -> Vec<Signal> {
        events.into_iter().filter_map(|e| self.apply(e)).collect()
    }

    pub fn apply(&mut self, event: &Value) -> Option<Signal> {
        let kind = str_of(event, "type");
        let data = event.get("data").unwrap_or(&Value::Null);
        let timestamp = str_of(event, "timestamp");
        let seq = int_of(event, "seq");
        self.now = timestamp.to_string();

        match kind {
            "session_snapshot" => {
                self.snapshot = Some((int_of(data, "snapshot_seq"), timestamp.to_string()));
                self.busy = matches!(str_of(data, "queen_busy_reason"), "llm" | "tool");
                // Replayed requests from before the snapshot don't redraw the question form, so it's seeded here.
                if data.get("awaiting_input").and_then(Value::as_bool).unwrap_or(false) {
                    let pending = questions_of(data.get("pending_questions"));
                    if !pending.is_empty() {
                        self.pending = pending;
                    }
                }
                return None;
            }
            "session_forked" => {
                let id = str_of(data, "new_session_id");
                return (!id.is_empty()).then(|| Signal::Forked(id.to_string()));
            }
            _ => {}
        }
        if !self.seen.insert(format!("{timestamp}|{seq}")) {
            return None;
        }
        // Events that matter whichever stream carries them.
        match kind {
            k if k.starts_with("task_") => return Some(Signal::Tasks),
            "trigger_fired" => {
                let task = str_of(data, "task");
                let text = if task.is_empty() {
                    format!("Schedule fired: {}", str_of(data, "name"))
                } else {
                    format!("Schedule fired: {} — {task}", str_of(data, "name"))
                };
                self.notice(&format!("trigger-{timestamp}"), text);
                return Some(Signal::Triggers);
            }
            k if k.starts_with("trigger_") => return Some(Signal::Triggers),
            "skill_install_requested" | "skill_install_decided" => return Some(Signal::SkillInstalls),
            "session_title_updated" => return Some(Signal::Title(str_of(data, "title").to_string())),
            "client_credential_form_requested" => return Some(Signal::CredentialForm(data.clone())),
            "colony_suggestion_requested" => return Some(Signal::ColonySuggestion(data.clone())),
            _ => {}
        }
        let stream = str_of(event, "stream_id");
        if let Some(worker) = stream.strip_prefix("worker") {
            // One anchor per worker, where its first event lands; what it did comes from the workers list.
            let id = format!("worker-{stream}");
            if !self.index.contains_key(&id) {
                self.upsert(&id, Kind::Worker { id: worker.trim_start_matches(':').to_string() });
            }
            return Some(Signal::Workers);
        }
        if stream != "queen" {
            return None;
        }
        let live = match &self.snapshot {
            Some((snap_seq, snap_time)) => !(seq <= *snap_seq && timestamp <= snap_time.as_str()),
            None => true,
        };
        let busy = |chat: &mut Self, value: bool| {
            if live {
                chat.busy = value;
            }
        };
        let exec = str_of(event, "execution_id");
        let iteration = int_of(data, "iteration");
        let inner = int_of(data, "inner_turn");

        match kind {
            "client_output_delta" | "llm_text_delta" => {
                let turn = self.inputs.range(..timestamp.to_string()).next_back().map_or("", String::as_str);
                let id = format!("queen-{exec}-{iteration}-{turn}");
                self.set_part(&id, Kind::Queen, inner, data);
                busy(self, true);
            }
            "llm_reasoning_delta" => {
                let id = format!("reason-{exec}-{iteration}-t{inner}");
                if !self.settled.contains(&id) {
                    self.set_part(&id, Kind::Thinking, 0, data);
                }
                busy(self, true);
            }
            "client_reasoning" => {
                let id = format!("reason-{exec}-{iteration}-t{inner}");
                self.parts.entry(id.clone()).or_default().insert(0, str_of(data, "reasoning").to_string());
                self.upsert(&id, Kind::Thinking);
                self.settled.insert(id);
            }
            "tool_call_started" => {
                if event.get("node_id").is_none_or(Value::is_null) {
                    return None;
                }
                let id = format!("tool-{exec}-{}", str_of(data, "tool_use_id"));
                let name = str_of(data, "tool_name").to_string();
                // A replayed start mustn't undo the finish that came after it.
                if !self.index.contains_key(&id) {
                    self.upsert(&id, Kind::Tool { name, state: ToolState::Running });
                }
                if let Some(input) = data.get("tool_input").and_then(readable) {
                    self.detail_mut(&id).input = Some(input);
                }
                busy(self, true);
            }
            "tool_call_completed" => {
                let id = format!("tool-{exec}-{}", str_of(data, "tool_use_id"));
                let failed = data.get("is_error").and_then(Value::as_bool).unwrap_or(false);
                let state = if failed { ToolState::Failed } else { ToolState::Done };
                self.upsert(&id, Kind::Tool { name: str_of(data, "tool_name").to_string(), state });
                if let Some(result) = data.get("result").and_then(readable) {
                    self.detail_mut(&id).result = Some(result);
                }
            }
            "client_input_received" => {
                let content = str_of(data, "content");
                if content.starts_with("<hive-internal>") {
                    return None;
                }
                let id = format!("user-input-{timestamp}");
                self.inputs.insert(timestamp.to_string());
                self.parts.entry(id.clone()).or_default().insert(0, strip_reminders(content));
                self.upsert(&id, Kind::User);
                let images: Vec<String> = data
                    .get("image_paths")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter_map(Value::as_str)
                    .map(str::to_string)
                    .collect();
                if !images.is_empty() {
                    self.detail_mut(&id).images = images;
                }
                self.pending.clear();
            }
            "client_input_requested" => {
                busy(self, false);
                let questions = questions_of(data.get("questions"));
                if !questions.is_empty() {
                    let text = match questions.as_slice() {
                        [one] => one.prompt.clone(),
                        many => many
                            .iter()
                            .enumerate()
                            .map(|(ix, q)| format!("{}. {}", ix + 1, q.prompt))
                            .collect::<Vec<_>>()
                            .join("\n"),
                    };
                    self.parts.entry(format!("ask-{timestamp}")).or_default().insert(0, text);
                    self.upsert(&format!("ask-{timestamp}"), Kind::Question);
                    self.pending = questions;
                }
            }
            "loop_state_changed" => {
                if matches!(str_of(data, "activity"), "awaiting_user" | "interrupted") {
                    busy(self, false);
                }
            }
            "context_usage_updated" => self.context_pct = data.get("usage_pct").and_then(Value::as_f64),
            "execution_started" | "node_loop_started" | "node_loop_iteration" => busy(self, true),
            "execution_completed" => busy(self, false),
            "execution_failed" => {
                self.notice(&format!("failed-{timestamp}"), format!("Error: {}", str_of(data, "error")))
            }
            "execution_paused" => {
                self.notice(&format!("paused-{timestamp}"), format!("Paused: {}", str_of(data, "reason")))
            }
            _ => {}
        }
        None
    }

    /// Store one inner turn's text and refresh the bubble that joins them.
    fn set_part(&mut self, id: &str, kind: Kind, inner: i64, data: &Value) {
        let part = self.parts.entry(id.to_string()).or_default().entry(inner).or_default();
        match data.get("snapshot").and_then(Value::as_str) {
            Some(snapshot) => *part = snapshot.to_string(),
            None => part.push_str(str_of(data, "content")),
        }
        self.upsert(id, kind);
    }

    fn notice(&mut self, id: &str, text: String) {
        self.parts.entry(id.to_string()).or_default().insert(0, text);
        self.upsert(id, Kind::Notice);
    }

    fn upsert(&mut self, id: &str, kind: Kind) {
        let text = self
            .parts
            .get(id)
            .map(|p| p.values().map(String::as_str).collect::<Vec<_>>().join("\n\n"))
            .unwrap_or_default();
        match self.index.get(id) {
            Some(&ix) => {
                self.items[ix].kind = kind;
                self.items[ix].text = text;
            }
            None => {
                self.index.insert(id.to_string(), self.items.len());
                self.items.push(Item {
                    id: id.to_string(),
                    kind,
                    text,
                    detail: Detail::default(),
                    at: self.now.clone(),
                });
            }
        }
    }

    /// The detail of an item `upsert` has made.
    fn detail_mut(&mut self, id: &str) -> &mut Detail {
        &mut self.items[self.index[id]].detail
    }

    /// Show a problem the server never reported, such as a failed send.
    pub fn local_notice(&mut self, text: String) {
        self.now.clear();
        let id = format!("local-{}", self.items.len());
        self.notice(&id, text);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn ev(kind: &str, seq: i64, data: Value) -> Value {
        json!({
            "type": kind,
            "stream_id": "queen",
            "node_id": "queen",
            "execution_id": "session_x",
            "timestamp": format!("2026-01-02T03:04:{seq:02}"),
            "seq": seq,
            "data": data,
        })
    }

    fn texts(chat: &Chat) -> Vec<(Kind, &str)> {
        chat.items.iter().map(|i| (i.kind.clone(), i.text.as_str())).collect()
    }

    #[test]
    fn replaces_the_reply_with_each_snapshot_and_joins_inner_turns() {
        let mut chat = Chat::default();
        chat.apply(&ev("client_input_received", 1, json!({ "content": "hi Ava" })));
        chat.apply(&ev(
            "client_output_delta",
            2,
            json!({ "iteration": 1, "inner_turn": 0, "content": "Hel", "snapshot": "Hel" }),
        ));
        chat.apply(&ev(
            "client_output_delta",
            3,
            json!({ "iteration": 1, "inner_turn": 0, "content": "lo", "snapshot": "Hello" }),
        ));
        chat.apply(&ev(
            "client_output_delta",
            4,
            json!({ "iteration": 1, "inner_turn": 1, "content": "Done.", "snapshot": "Done." }),
        ));

        assert_eq!(texts(&chat), vec![(Kind::User, "hi Ava"), (Kind::Queen, "Hello\n\nDone.")]);
        assert!(chat.busy);
    }

    #[test]
    fn stamps_each_item_with_its_first_events_time() {
        let mut chat = Chat::default();
        chat.apply(&ev("client_input_received", 7, json!({ "content": "hi" })));
        chat.local_notice("Couldn't send".into());

        assert_eq!(chat.items[0].time(), "03:04");
        assert_eq!(chat.items[1].time(), "");
    }

    #[test]
    fn applying_the_same_events_twice_changes_nothing() {
        let events = vec![
            ev("client_input_received", 1, json!({ "content": "hi" })),
            ev("client_output_delta", 2, json!({ "iteration": 1, "snapshot": "Hello" })),
            ev("tool_call_started", 3, json!({ "tool_use_id": "t1", "tool_name": "web_search" })),
            ev("tool_call_completed", 4, json!({ "tool_use_id": "t1", "tool_name": "web_search", "is_error": false })),
        ];
        let mut chat = Chat::default();
        chat.apply_all(&events);
        chat.apply_all(&events);
        // The stream renumbers seq, so the second pass isn't caught by the seen-set alone.
        let renumbered: Vec<Value> = events
            .iter()
            .map(|e| {
                let mut e = e.clone();
                e["seq"] = json!(e["seq"].as_i64().unwrap() + 100);
                e
            })
            .collect();
        chat.apply_all(&renumbered);

        assert_eq!(
            texts(&chat),
            vec![
                (Kind::User, "hi"),
                (Kind::Queen, "Hello"),
                (Kind::Tool { name: "web_search".into(), state: ToolState::Done }, ""),
            ]
        );
    }

    #[test]
    fn a_turn_after_a_restart_gets_its_own_bubble() {
        let mut chat = Chat::default();
        chat.apply(&ev("client_input_received", 1, json!({ "content": "first" })));
        chat.apply(&ev("client_output_delta", 2, json!({ "iteration": 0, "snapshot": "one" })));
        chat.apply(&ev("client_input_received", 3, json!({ "content": "second" })));
        chat.apply(&ev("client_output_delta", 4, json!({ "iteration": 0, "snapshot": "two" })));

        assert_eq!(texts(&chat).iter().map(|t| t.1).collect::<Vec<_>>(), vec!["first", "one", "second", "two"]);
    }

    #[test]
    fn a_re_sent_stream_keeps_each_reply_in_its_own_turn() {
        let events = vec![
            ev("client_input_received", 1, json!({ "content": "first" })),
            ev("client_output_delta", 2, json!({ "iteration": 0, "snapshot": "one" })),
            ev("client_input_received", 3, json!({ "content": "second" })),
            ev("client_output_delta", 4, json!({ "iteration": 0, "snapshot": "two" })),
        ];
        let mut chat = Chat::default();
        chat.apply_all(&events);
        // A reconnect re-sends the stream with new seqs.
        let renumbered: Vec<Value> = events
            .iter()
            .map(|e| {
                let mut e = e.clone();
                e["seq"] = json!(e["seq"].as_i64().unwrap() + 100);
                e
            })
            .collect();
        chat.apply_all(&renumbered);

        assert_eq!(texts(&chat).iter().map(|t| t.1).collect::<Vec<_>>(), vec!["first", "one", "second", "two"]);
    }

    #[test]
    fn older_history_loaded_later_keeps_each_reply_in_its_own_turn() {
        let mut chat = Chat::default();
        chat.apply(&ev("client_input_received", 3, json!({ "content": "second" })));
        chat.apply(&ev("client_output_delta", 4, json!({ "iteration": 0, "snapshot": "two" })));
        chat.apply(&ev("client_input_received", 1, json!({ "content": "first" })));
        chat.apply(&ev("client_output_delta", 2, json!({ "iteration": 0, "snapshot": "one" })));
        chat.apply(&ev("client_output_delta", 5, json!({ "iteration": 0, "snapshot": "two, more" })));

        let mut replies: Vec<&str> =
            chat.items.iter().filter(|i| i.kind == Kind::Queen).map(|i| i.text.as_str()).collect();
        replies.sort();
        assert_eq!(replies, vec!["one", "two, more"]);
    }

    #[test]
    fn stops_being_busy_when_the_queen_waits_for_you() {
        let mut chat = Chat::default();
        chat.apply(&ev("client_output_delta", 1, json!({ "iteration": 1, "snapshot": "ok" })));
        assert!(chat.busy);
        chat.apply(&ev("loop_state_changed", 2, json!({ "activity": "awaiting_user", "park_reason": "turn_done" })));
        assert!(!chat.busy);
    }

    #[test]
    fn events_from_before_the_snapshot_draw_but_dont_change_busy() {
        let mut chat = Chat::default();
        chat.apply(&json!({ "type": "session_snapshot", "timestamp": "2026-01-02T03:04:09", "seq": 0, "data": { "snapshot_seq": 9, "queen_busy_reason": null } }));
        chat.apply(&ev("client_output_delta", 5, json!({ "iteration": 1, "snapshot": "earlier" })));

        assert_eq!(texts(&chat), vec![(Kind::Queen, "earlier")]);
        assert!(!chat.busy);
    }

    #[test]
    fn hides_internal_input_and_other_streams() {
        let mut chat = Chat::default();
        chat.apply(&ev("client_input_received", 1, json!({ "content": "<hive-internal>wake</hive-internal>" })));
        let mut judge = ev("client_output_delta", 2, json!({ "snapshot": "judge text" }));
        judge["stream_id"] = json!("judge");
        chat.apply(&judge);

        assert!(chat.items.is_empty());
    }

    #[test]
    fn gives_each_worker_one_anchor_and_asks_for_the_workers_list() {
        let mut chat = Chat::default();
        let mut first = ev("node_loop_started", 1, json!({}));
        first["stream_id"] = json!("worker:w-ivy");
        let mut second = ev("subagent_report", 2, json!({ "summary": "done" }));
        second["stream_id"] = json!("worker:w-ivy");

        assert_eq!(chat.apply(&first), Some(Signal::Workers));
        chat.apply(&second);

        assert_eq!(texts(&chat), vec![(Kind::Worker { id: "w-ivy".into() }, "")]);
    }

    #[test]
    fn keeps_questions_pending_until_answered() {
        let mut chat = Chat::default();
        chat.apply(&ev(
            "client_input_requested",
            1,
            json!({ "questions": [{ "id": "q1", "prompt": "Which city?", "options": ["Oslo", "Lima"] }] }),
        ));
        assert_eq!(
            chat.pending,
            vec![Question {
                id: "q1".into(),
                prompt: "Which city?".into(),
                options: vec!["Oslo".into(), "Lima".into()]
            }]
        );
        assert_eq!(texts(&chat), vec![(Kind::Question, "Which city?")]);

        chat.apply(&ev("client_input_received", 2, json!({ "content": "Oslo" })));
        assert!(chat.pending.is_empty());
    }

    #[test]
    fn answers_one_question_bare_and_several_as_prompt_answer_lines() {
        let one = vec![Question { id: "q1".into(), prompt: "Which city?".into(), options: vec![] }];
        let two = vec![one[0].clone(), Question { id: "q2".into(), prompt: "When?".into(), options: vec![] }];

        assert_eq!(answer_text(&one, &["Oslo".into()]), "Oslo");
        assert_eq!(
            answer_text(&two, &["Oslo".into(), "Friday".into()]),
            "\"Which city?\"=\"Oslo\"\n\"When?\"=\"Friday\""
        );
    }

    #[test]
    fn keeps_the_images_sent_with_a_message_but_not_the_servers_note() {
        let mut chat = Chat::default();
        let content = "look

<system-reminder>
[Attachments saved to disk]
</system-reminder>";
        chat.apply(&ev(
            "client_input_received",
            1,
            json!({ "content": content, "image_paths": ["data/attachments/1_0.png"] }),
        ));

        assert_eq!(chat.items[0].text, "look");
        assert_eq!(chat.items[0].detail.images, vec!["data/attachments/1_0.png".to_string()]);
    }

    #[test]
    fn shows_errors_and_follows_a_fork_and_a_new_title() {
        let mut chat = Chat::default();
        chat.apply(&ev("execution_failed", 1, json!({ "error": "model refused" })));
        let forked = chat.apply(&ev("session_forked", 2, json!({ "new_session_id": "session_y" })));
        let titled = chat.apply(&ev("session_title_updated", 3, json!({ "title": "Trip to Oslo" })));

        assert_eq!(texts(&chat), vec![(Kind::Notice, "Error: model refused")]);
        assert_eq!(forked, Some(Signal::Forked("session_y".into())));
        assert_eq!(titled, Some(Signal::Title("Trip to Oslo".into())));
    }

    #[test]
    fn final_reasoning_wins_over_later_deltas() {
        let mut chat = Chat::default();
        chat.apply(&ev("client_reasoning", 1, json!({ "iteration": 1, "inner_turn": 0, "reasoning": "full thought" })));
        chat.apply(&ev("llm_reasoning_delta", 2, json!({ "iteration": 1, "inner_turn": 0, "snapshot": "full" })));

        assert_eq!(texts(&chat), vec![(Kind::Thinking, "full thought")]);
    }
}
