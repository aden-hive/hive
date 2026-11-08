//! A session's plan: the tasks the queen broke the work into, as the web's Action Plan shows them.

use gpui_kit::assets::IconName;
use gpui_kit::base::{h_flex, v_flex};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{Icon, Sizable as _, StyledExt as _, Theme};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use crate::api::Api;
use crate::ui;

/// The session's task list; a session without one yet reads as an empty list.
pub fn load(api: &Api, session_id: &str) -> anyhow::Result<Value> {
    match api.get(&format!("/sessions/{session_id}/tasks")) {
        Err(e) if e.to_string().starts_with("HTTP 404") => Ok(json!({ "tasks": [] })),
        other => other,
    }
}

/// The tasks worth showing: not internal, dropped or archived, as the web hides them.
pub fn visible(plan: &Value) -> Vec<Value> {
    plan["tasks"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|t| {
            !t["metadata"]["_internal"].as_bool().unwrap_or(false)
                && !matches!(t["status"].as_str(), Some("abandoned" | "archived"))
        })
        .cloned()
        .collect()
}

fn text(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

/// The goal, progress and one row per task.
pub fn render(plan: &Option<Result<Value, String>>, theme: &Theme) -> AnyElement {
    let plan = match plan {
        None => return Spinner::new().small().into_any_element(),
        Some(Err(e)) => return ui::error_line(e.clone(), theme).into_any_element(),
        Some(Ok(p)) => p,
    };
    let tasks = visible(plan);
    if tasks.is_empty() {
        return ui::muted("No plan yet. The queen writes one when she breaks the work down.", theme).into_any_element();
    }
    let done = tasks.iter().filter(|t| t["status"] == "completed").count();
    let goal = Some(text(&plan["meta"]["goal"])).filter(|g| !g.is_empty()).unwrap_or_else(|| "Tasks".into());
    v_flex()
        .gap_2()
        .child(
            h_flex().justify_between().child(div().text_sm().font_medium().child(goal)).child(
                div().text_xs().text_color(theme.muted_foreground).child(format!("{done}/{} done", tasks.len())),
            ),
        )
        .children(tasks.iter().map(|t| {
            let status = t["status"].as_str().unwrap_or_default();
            let (icon, color) = match status {
                "completed" => (IconName::SquareCheck, theme.success),
                "in_progress" => (IconName::LoaderCircle, theme.warning),
                _ => (IconName::Square, theme.muted_foreground),
            };
            let label = if status == "in_progress" {
                Some(text(&t["active_form"])).filter(|s| !s.is_empty()).unwrap_or_else(|| text(&t["subject"]))
            } else {
                text(&t["subject"])
            };
            h_flex().gap_2().items_start().text_sm().child(Icon::new(icon).small().text_color(color)).child(
                div()
                    .when(status == "completed", |d| d.line_through().text_color(theme.muted_foreground))
                    .child(format!("#{} {label}", text(&t["id"]))),
            )
        }))
        .into_any_element()
}

#[cfg(test)]
mod tests {
    // Not `super::*`: GPUI's own `test` macro would shadow the standard one.
    use super::visible;
    use serde_json::json;

    #[test]
    fn hides_internal_dropped_and_archived_tasks() {
        let plan = json!({ "tasks": [
            { "id": 1, "status": "completed" },
            { "id": 2, "status": "abandoned" },
            { "id": 3, "status": "archived" },
            { "id": 4, "status": "pending", "metadata": { "_internal": true } },
            { "id": 5, "status": "in_progress" },
        ] });

        assert_eq!(visible(&plan).iter().map(|t| t["id"].as_i64().unwrap()).collect::<Vec<_>>(), vec![1, 5]);
    }
}
