//! A queen that runs on Claude Code: the conversations other queens hold with her by letter, read
//! only. Mirrors `frontend/src/pages/claude-code-queen.tsx`.

use gpui_kit::assets::IconName;
use gpui_kit::base::{h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _, Theme};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::Value;

use super::{flag, text};
use crate::api::{api, encode};
use crate::{bg, ui};

pub struct ClaudeCodePage {
    queen_id: String,
    /// `None` while loading; `Some(Ok(None))` when no Claude Code queen has this id.
    queen: Option<Result<Option<Value>, String>>,
    selected: Option<String>,
    transcript: Option<Result<Vec<Value>, String>>,
    tasks: Vec<Task<()>>,
}

/// "3 letters · 2026-11-07 14:05", as the conversation list reads.
fn conversation_line(conversation: &Value) -> String {
    let letters = conversation["letters"].as_i64().unwrap_or(0);
    let noun = if letters == 1 { "letter" } else { "letters" };
    let when = text(conversation, "last_at").replace('T', " ").chars().take(16).collect::<String>();
    if when.is_empty() { format!("{letters} {noun}") } else { format!("{letters} {noun} · {when}") }
}

/// The header's second line: "Head of Code · API key · acceptEdits · claude-x · read only".
fn summary(queen: &Value) -> String {
    let auth = if text(queen, "auth") == "subscription" { "subscription" } else { "API key" };
    let mut parts = vec![text(queen, "title"), auth.to_string(), text(queen, "permission_mode")];
    if !text(queen, "model").is_empty() {
        parts.push(text(queen, "model"));
    }
    parts.push("read only".into());
    parts.into_iter().filter(|p| !p.is_empty()).collect::<Vec<_>>().join(" · ")
}

impl ClaudeCodePage {
    pub fn new(queen_id: String, _window: &mut Window, cx: &mut Context<Self>) -> Self {
        let mut page = Self { queen_id, queen: None, selected: None, transcript: None, tasks: Vec::new() };
        page.load(cx);
        page
    }

    fn load(&mut self, cx: &mut Context<Self>) {
        let (api, id) = (api(cx), self.queen_id.clone());
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let body = api.get("/claude-code-queens")?;
                anyhow::Ok(body["queens"].as_array().into_iter().flatten().find(|q| q["id"] == id.as_str()).cloned())
            },
            |this: &mut Self, loaded, cx| {
                // Open the newest conversation, as the web page does, unless one is already open.
                if let Ok(Some(queen)) = &loaded
                    && this.selected.is_none()
                    && let Some(first) = queen["conversations"].as_array().and_then(|c| c.first())
                {
                    let session = text(first, "session_id");
                    this.select(session, cx);
                } else if let Some(session) = this.selected.clone() {
                    this.select(session, cx);
                }
                this.queen = Some(loaded.map_err(|e| e.to_string()));
            },
        ));
    }

    fn select(&mut self, session_id: String, cx: &mut Context<Self>) {
        self.selected = Some(session_id.clone());
        let (api, queen) = (api(cx), self.queen_id.clone());
        self.tasks.push(bg::spawn(
            cx,
            move || api.get(&format!("/claude-code-queens/{queen}/conversations/{}", encode(&session_id))),
            |this: &mut Self, got, _| {
                this.transcript =
                    Some(got.map(|b| b["entries"].as_array().cloned().unwrap_or_default()).map_err(|e| e.to_string()))
            },
        ));
        cx.notify();
    }

    fn render_entry(&self, ix: usize, entry: &Value, peer: &str, theme: &Theme) -> AnyElement {
        let body = text(entry, "text");
        match text(entry, "kind").as_str() {
            "letter" => v_flex()
                .gap_1()
                .p_3()
                .rounded_lg()
                .bg(theme.muted)
                .child(
                    h_flex()
                        .gap_1()
                        .text_xs()
                        .text_color(theme.muted_foreground)
                        .child(Icon::new(IconName::Mail).xsmall())
                        .child(format!("Letter from {peer}")),
                )
                .child(div().text_sm().child(body))
                .into_any_element(),
            "tool" => h_flex()
                .gap_1p5()
                .text_xs()
                .text_color(if flag(entry, "error") { theme.danger } else { theme.muted_foreground })
                .child(Icon::new(IconName::Wrench).xsmall())
                .child(div().font_medium().child(text(entry, "tool")))
                .child(div().truncate().child(ui::clip(&body, 160)))
                .into_any_element(),
            "result" => v_flex()
                .gap_1()
                .pl_3()
                .border_l_2()
                .border_color(theme.success)
                .child(div().text_xs().text_color(theme.muted_foreground).child(format!("Sent back to {peer}")))
                .child(ui::markdown(SharedString::from(format!("cc-result-{ix}")), body, theme))
                .into_any_element(),
            _ => ui::markdown(SharedString::from(format!("cc-text-{ix}")), body, theme).into_any_element(),
        }
    }
}

impl Render for ClaudeCodePage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let refresh = cx.listener(|this, _, _, cx| this.load(cx));
        let theme = cx.theme().clone();
        let queen = match &self.queen {
            Some(Ok(Some(q))) => Some(q.clone()),
            _ => None,
        };
        let header = h_flex()
            .gap_3()
            .px_6()
            .py_4()
            .border_b_1()
            .border_color(theme.border)
            .child(
                div()
                    .size(px(36.))
                    .rounded_full()
                    .flex()
                    .items_center()
                    .justify_center()
                    .bg(theme.muted)
                    .child(Icon::new(IconName::SquareTerminal).small()),
            )
            .child(
                v_flex()
                    .flex_1()
                    .min_w_0()
                    .child(
                        div()
                            .text_lg()
                            .font_semibold()
                            .child(queen.as_ref().map(|q| text(q, "name")).unwrap_or_else(|| self.queen_id.clone())),
                    )
                    .child(
                        div()
                            .text_xs()
                            .text_color(theme.muted_foreground)
                            .child(queen.as_ref().map(summary).unwrap_or_default()),
                    ),
            )
            .child(
                Button::new("refresh").small().ghost().icon(IconName::RefreshCw).tooltip("Refresh").on_click(refresh),
            );

        let body: AnyElement = match &self.queen {
            None => v_flex().p_8().child(Spinner::new()).into_any_element(),
            Some(Err(e)) => v_flex().p_8().child(ui::error_line(e.clone(), &theme)).into_any_element(),
            Some(Ok(None)) => v_flex()
                .p_8()
                .child(ui::muted(
                    format!(
                        "No queen {} runs on Claude Code here (queen_mail.claude_code in configuration.json).",
                        self.queen_id
                    ),
                    &theme,
                ))
                .into_any_element(),
            Some(Ok(Some(queen))) => {
                let conversations = queen["conversations"].as_array().cloned().unwrap_or_default();
                let open = conversations.iter().find(|c| Some(text(c, "session_id")) == self.selected).cloned();
                let peer = open.as_ref().map(|c| text(c, "peer_name")).unwrap_or_default();
                let list = conversations.iter().enumerate().map(|(ix, c)| {
                    let session = text(c, "session_id");
                    let active = self.selected.as_deref() == Some(session.as_str());
                    v_flex()
                        .id(("cc-conversation", ix))
                        .px_2()
                        .py_2()
                        .rounded_md()
                        .cursor_pointer()
                        .when(active, |r| r.bg(theme.list_active))
                        .when(!active, |r| r.hover(|r| r.bg(theme.list_hover)))
                        .child(
                            h_flex()
                                .gap_1p5()
                                .text_sm()
                                .font_medium()
                                .child(text(c, "peer_name"))
                                .when(flag(c, "running"), |r| r.child(ui::dot(theme.success))),
                        )
                        .child(div().text_xs().text_color(theme.muted_foreground).child(conversation_line(c)))
                        .on_click(cx.listener(move |this, _, _, cx| this.select(session.clone(), cx)))
                });
                let transcript: AnyElement = match (&open, &self.transcript) {
                    (None, _) => ui::muted("Pick a conversation.", &theme).into_any_element(),
                    (Some(_), None) => Spinner::new().small().into_any_element(),
                    (Some(_), Some(Err(e))) => ui::error_line(e.clone(), &theme).into_any_element(),
                    (Some(c), Some(Ok(entries))) => v_flex()
                        .gap_3()
                        .child(div().text_xs().text_color(theme.muted_foreground).child(format!(
                            "With {} ({}) · what she ends each turn with goes back to {}",
                            text(c, "peer_name"),
                            text(c, "peer"),
                            text(c, "peer_name")
                        )))
                        .children(entries.iter().enumerate().map(|(ix, e)| self.render_entry(ix, e, &peer, &theme)))
                        .into_any_element(),
                };
                v_flex()
                    .flex_1()
                    .min_h_0()
                    .when(text(queen, "auth") == "subscription", |c| {
                        c.child(
                            div().mx_6().mt_3().px_3().py_2().rounded_md().bg(theme.muted).text_xs().child(
                                "She runs on a Claude subscription signed in on this computer. Running a plan unattended \
                                 for other agents may break its terms, and the account may be limited or closed: that is at \
                                 your own risk. An Anthropic API key is the supported way.",
                            ),
                        )
                    })
                    .child(
                        h_flex()
                            .flex_1()
                            .min_h_0()
                            .child(
                                div()
                                    .id("cc-conversations")
                                    .w(px(256.))
                                    .h_full()
                                    .flex_shrink_0()
                                    .border_r_1()
                                    .border_color(theme.border)
                                    .overflow_y_scroll()
                                    .p_2()
                                    .child(
                                        div()
                                            .px_2()
                                            .py_1p5()
                                            .text_xs()
                                            .text_color(theme.muted_foreground)
                                            .child("CONVERSATIONS"),
                                    )
                                    .when(conversations.is_empty(), |c| {
                                        c.child(ui::muted("No queen has written to her yet.", &theme))
                                    })
                                    .children(list),
                            )
                            .child(div().id("cc-transcript").flex_1().h_full().overflow_y_scroll().px_6().py_4().child(transcript)),
                    )
                    .into_any_element()
            }
        };
        v_flex().size_full().child(header).child(body)
    }
}

#[cfg(test)]
mod tests {
    // Not `super::*`: GPUI's own `test` macro would shadow the standard one.
    use super::{conversation_line, summary};
    use serde_json::json;

    #[test]
    fn summarises_the_queen_and_her_conversations() {
        let queen =
            json!({ "title": "Head of Code", "auth": "subscription", "permission_mode": "acceptEdits", "model": null });
        assert_eq!(summary(&queen), "Head of Code · subscription · acceptEdits · read only");
        assert_eq!(
            conversation_line(&json!({ "letters": 1, "last_at": "2026-11-07T14:05:09" })),
            "1 letter · 2026-11-07 14:05"
        );
        assert_eq!(conversation_line(&json!({ "letters": 3, "last_at": null })), "3 letters");
    }
}
