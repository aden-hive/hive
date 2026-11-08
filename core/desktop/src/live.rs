//! Which sessions are running and what they're doing, from `GET /api/sessions/live`, for the
//! sidebar's status dots.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use gpui_kit::*;
use serde_json::Value;

use crate::api::{StreamEnd, api};

/// How a queen or colony is doing, as the web sidebar's dots show it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum State {
    /// Thinking, running a tool, or has workers at it.
    Working,
    /// Stopped, or waiting for an answer.
    Waiting,
    /// Has a running session doing nothing.
    Idle,
}

pub struct Live {
    rows: Vec<Value>,
    /// Why the server can't reach the model provider, while it can't (`network` in the snapshot).
    degraded: Option<String>,
    stop: Arc<AtomicBool>,
    _task: Task<()>,
}

impl Drop for Live {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
    }
}

impl Live {
    pub fn new(cx: &mut Context<Self>) -> Self {
        let (tx, rx) = smol::channel::unbounded::<Value>();
        let stop = Arc::new(AtomicBool::new(false));
        let api = api(cx);
        let thread_stop = stop.clone();
        std::thread::spawn(move || {
            while !thread_stop.load(Ordering::Relaxed) {
                // Snapshots come as named frames; each carries every live session.
                let ended =
                    api.stream("/sessions/live", &thread_stop, |frame| tx.send_blocking(frame["data"].clone()).is_ok());
                if matches!(ended, Ok(StreamEnd::Stopped)) {
                    return;
                }
                std::thread::sleep(Duration::from_secs(5));
            }
        });
        let task = cx.spawn(async move |this, cx| {
            while let Ok(snapshot) = rx.recv().await {
                if this
                    .update(cx, |live, cx| {
                        live.rows = snapshot["sessions"].as_array().cloned().unwrap_or_default();
                        let network = &snapshot["network"];
                        live.degraded = network["degraded"]
                            .as_bool()
                            .unwrap_or(false)
                            .then(|| network["reason"].as_str().unwrap_or("no reason given").to_string());
                        cx.notify();
                    })
                    .is_err()
                {
                    break;
                }
            }
        });
        Self { rows: Vec::new(), degraded: None, stop, _task: task }
    }

    pub fn degraded(&self) -> Option<&str> {
        self.degraded.as_deref()
    }

    /// A queen's direct chats; colony sessions count toward their colony instead.
    pub fn queen(&self, queen_id: &str) -> Option<State> {
        state(self.rows.iter().filter(|r| r["queen_id"] == queen_id && r["colony_id"].is_null()))
    }

    pub fn colony(&self, colony: &str) -> Option<State> {
        state(self.rows.iter().filter(|r| r["colony_id"] == colony))
    }
}

fn is_working(row: &Value) -> bool {
    row["is_executing"].as_bool().unwrap_or(false) || row["active_worker_count"].as_i64().unwrap_or(0) > 0
}

fn state<'a>(rows: impl Iterator<Item = &'a Value>) -> Option<State> {
    let rows: Vec<&Value> = rows.collect();
    if rows.is_empty() {
        None
    } else if rows.iter().any(|r| is_working(r)) {
        Some(State::Working)
    } else if rows
        .iter()
        .any(|r| r["interrupted"].as_bool().unwrap_or(false) || r["awaiting_input"].as_bool().unwrap_or(false))
    {
        Some(State::Waiting)
    } else {
        Some(State::Idle)
    }
}

#[cfg(test)]
mod tests {
    // Not `super::*`: GPUI's own `test` macro would shadow the standard one.
    use std::sync::Arc;
    use std::sync::atomic::AtomicBool;

    use gpui_kit::Task;
    use serde_json::json;

    use super::{Live, State};

    #[test]
    fn working_beats_waiting_beats_idle_and_colonies_count_apart() {
        let rows = vec![
            json!({ "queen_id": "queen_ava", "colony_id": null, "is_executing": false, "awaiting_input": true }),
            json!({ "queen_id": "queen_ava", "colony_id": null, "is_executing": true }),
            json!({ "queen_id": "queen_ava", "colony_id": "ava_research", "active_worker_count": 0, "interrupted": true }),
            json!({ "queen_id": "queen_ivy", "colony_id": null, "is_executing": false }),
        ];
        let live = Live { rows, degraded: None, stop: Arc::new(AtomicBool::new(false)), _task: Task::ready(()) };

        assert_eq!(live.queen("queen_ava"), Some(State::Working));
        assert_eq!(live.colony("ava_research"), Some(State::Waiting));
        assert_eq!(live.queen("queen_ivy"), Some(State::Idle));
        assert_eq!(live.queen("queen_zed"), None);
    }
}
