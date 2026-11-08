//! Where the app opens: a greeting, a box to start a chat with any queen, who's working, the
//! queens themselves, and the user's prompts as quick starts. Mirrors `frontend/src/pages/home.tsx`
//! without its featured catalog and animations.

use std::collections::HashSet;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{InputEvent, Textarea, TextareaState};
use gpui_kit::component::{ActiveTheme as _, Sizable as _, StyledExt as _};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::Value;

use super::prompts::queen_for_category;
use super::{flag, text};
use crate::api::{Api, Queen, StreamEnd, api};
use crate::shell::{Route, Shell};
use crate::{avatars, bg, ui};

/// The queens as small chips to pick one from, each with her picture; `selected` is drawn as
/// chosen. The prompts page uses it too.
pub(super) fn queen_chips<V: 'static>(
    id: &'static str,
    queens: &[Queen],
    selected: Option<&str>,
    cx: &mut Context<V>,
    on_pick: impl Fn(&mut V, &Queen, &mut Window, &mut Context<V>) + Clone + 'static,
) -> Div {
    let mut row = h_flex().gap_1p5().flex_wrap();
    for (ix, queen) in queens.iter().enumerate() {
        let picture = avatars::avatar(queen, px(20.), cx);
        let listener = cx.listener({
            let (queen, on_pick) = (queen.clone(), on_pick.clone());
            move |this, _: &ClickEvent, window, cx| on_pick(this, &queen, window, cx)
        });
        let chosen = selected == Some(queen.id.as_str());
        // Two queens can share a name; their roles tell them apart.
        let label = if queens.iter().filter(|q| q.name == queen.name).count() > 1 {
            format!("{} · {}", queen.name, ui::role(&queen.title))
        } else {
            queen.name.clone()
        };
        let theme = cx.theme();
        row = row.child(
            h_flex()
                .id((id, ix))
                .gap_1p5()
                .pl_1()
                .pr_2p5()
                .py_1()
                .rounded_full()
                .border_1()
                .cursor_pointer()
                .text_sm()
                .when(chosen, |chip| chip.border_color(theme.primary).bg(theme.list_active).font_medium())
                .when(!chosen, |chip| chip.border_color(theme.border).hover(|chip| chip.bg(theme.list_hover)))
                .child(picture)
                .child(label)
                .on_click(listener),
        );
    }
    row
}

/// The queen ids with a direct chat working right now, from one `/sessions/live` snapshot. Colony
/// sessions are left out, as the web's `byQueen` does.
fn working_queens(snapshot: &Value) -> HashSet<String> {
    snapshot["sessions"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|s| flag(s, "is_executing") && s["colony_id"].is_null())
        .map(|s| text(s, "queen_id"))
        .filter(|id| !id.is_empty())
        .collect()
}

/// Keep the live-sessions feed open and pass on who's working at each snapshot, reconnecting when
/// it drops.
fn watch_live(api: &Api, stop: &AtomicBool, tx: &smol::channel::Sender<HashSet<String>>) {
    while !stop.load(Ordering::Relaxed) {
        let ended = api.stream("/sessions/live", stop, |event| {
            event["event"] != "snapshot" || tx.send_blocking(working_queens(&event["data"])).is_ok()
        });
        if matches!(ended, Ok(StreamEnd::Stopped)) || tx.is_closed() {
            return;
        }
        std::thread::sleep(Duration::from_secs(5));
    }
}

pub struct HomePage {
    shell: WeakEntity<Shell>,
    /// The user's display name from their profile; "" until it loads, or if they set none.
    name: String,
    composer: Entity<TextareaState>,
    /// Who the composer's message goes to.
    picked: Option<String>,
    prompts: Vec<Value>,
    working: HashSet<String>,
    error: Option<String>,
    stop: Arc<AtomicBool>,
    prompts_task: Option<Task<()>>,
    tasks: Vec<Task<()>>,
    _subscriptions: Vec<Subscription>,
}

impl Drop for HomePage {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
    }
}

impl HomePage {
    pub fn new(shell: WeakEntity<Shell>, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let composer = cx.new(|cx| {
            TextareaState::new(window, cx)
                .auto_grow(3, 12)
                .submit_on_enter(true)
                .placeholder("Describe a task for the hive…")
        });
        let mut subscriptions = vec![cx.subscribe_in(&composer, window, |this, _, event: &InputEvent, window, cx| {
            if let InputEvent::PressEnter { shift: false, .. } = event {
                this.send(window, cx);
            }
        })];
        subscriptions.push(cx.observe(&composer, |_, _, cx| cx.notify()));
        // The queens come from the shell, which may still be loading them. The shell also changes
        // on every navigation, the moment to pick up prompts written on the Prompts page.
        if let Some(shell) = shell.upgrade() {
            subscriptions.push(cx.observe(&shell, |this, _, cx| {
                this.load_prompts(cx);
                cx.notify();
            }));
        }
        let mut page = Self {
            shell,
            name: String::new(),
            composer,
            picked: None,
            prompts: Vec::new(),
            working: HashSet::new(),
            error: None,
            stop: Arc::new(AtomicBool::new(false)),
            prompts_task: None,
            tasks: Vec::new(),
            _subscriptions: subscriptions,
        };
        page.load(cx);
        page.watch(cx);
        page
    }

    /// Neither the name nor the prompts are needed to start a chat, so a failure leaves its part empty.
    fn load(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/config/profile"),
            |this: &mut Self, profile, _| {
                if let Ok(profile) = profile {
                    this.name = text(&profile, "displayName").trim().to_string();
                }
            },
        ));
        self.load_prompts(cx);
    }

    /// Replacing the task drops a load still in flight, so only the newest answer lands.
    fn load_prompts(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.prompts_task = Some(bg::spawn(
            cx,
            move || api.get("/prompts"),
            |this: &mut Self, prompts, _| {
                if let Ok(prompts) = prompts {
                    this.prompts = prompts["prompts"].as_array().cloned().unwrap_or_default();
                }
            },
        ));
    }

    /// Follow who's working on a thread, as the feed is a stream that stays open.
    fn watch(&mut self, cx: &mut Context<Self>) {
        let (tx, rx) = smol::channel::unbounded();
        let api = api(cx);
        let stop = self.stop.clone();
        std::thread::spawn(move || watch_live(&api, &stop, &tx));
        self.tasks.push(cx.spawn(async move |this, cx| {
            while let Ok(working) = rx.recv().await {
                let updated = this.update(cx, |view, cx| {
                    view.working = working;
                    cx.notify();
                });
                if updated.is_err() {
                    break;
                }
            }
        }));
    }

    fn queens(&self, cx: &App) -> Vec<Queen> {
        self.shell.upgrade().map(|s| s.read(cx).queens().to_vec()).unwrap_or_default()
    }

    fn send(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let message = self.composer.read(cx).value().trim().to_string();
        if message.is_empty() {
            return;
        }
        let Some(queen_id) = self.picked.clone() else {
            self.error = Some("Pick who you want to talk to first.".into());
            cx.notify();
            return;
        };
        self.error = None;
        self.composer.update(cx, |s, cx| s.set_value("", window, cx));
        self.shell.update(cx, |shell, cx| shell.chat_with(&queen_id, message, true, window, cx)).ok();
    }

    /// Put a prompt in the composer, and pick its category's queen if no one is picked yet.
    fn start_from(&mut self, prompt: &Value, window: &mut Window, cx: &mut Context<Self>) {
        let content = text(prompt, "content");
        self.composer.update(cx, |s, cx| {
            s.set_value(content, window, cx);
            s.focus(window, cx);
        });
        if self.picked.is_none()
            && let Some(queen) = queen_for_category(&text(prompt, "category"))
            && self.queens(cx).iter().any(|q| q.id == queen)
        {
            self.picked = Some(queen.to_string());
        }
        self.error = None;
        cx.notify();
    }

    fn render_queens(&self, queens: &[Queen], cx: &mut Context<Self>) -> AnyElement {
        let mut cards = Vec::new();
        for (ix, queen) in queens.iter().enumerate() {
            let picture = avatars::avatar(queen, px(40.), cx);
            let open = cx.listener({
                let id = queen.id.clone();
                move |this, _: &ClickEvent, window, cx| {
                    this.shell.update(cx, |shell, cx| shell.go(Route::Queen(id.clone()), window, cx)).ok();
                }
            });
            let working = self.working.contains(&queen.id);
            let theme = cx.theme();
            cards.push(
                h_flex()
                    .id(("queen-card", ix))
                    .w(px(212.))
                    .gap_3()
                    .px_3()
                    .py_3()
                    .rounded_lg()
                    .border_1()
                    .border_color(theme.border)
                    .bg(theme.background)
                    .cursor_pointer()
                    .hover(|card| card.bg(theme.list_hover))
                    .child(picture)
                    .child(
                        v_flex()
                            .min_w_0()
                            .flex_1()
                            .child(div().text_sm().font_medium().truncate().child(queen.name.clone()))
                            .child(
                                div()
                                    .text_xs()
                                    .text_color(theme.muted_foreground)
                                    .truncate()
                                    .child(ui::role(&queen.title).to_string()),
                            ),
                    )
                    .when(working, |card| card.child(ui::dot(theme.success)))
                    .on_click(open),
            );
        }
        h_flex().gap_3().flex_wrap().children(cards).into_any_element()
    }

    fn render_prompts(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let cards = self.prompts.iter().rev().enumerate().map(|(ix, prompt)| {
            let prompt = prompt.clone();
            v_flex()
                .id(("quick-start", ix))
                .w(px(290.))
                .gap_1()
                .px_3()
                .py_2p5()
                .rounded_lg()
                .border_1()
                .border_color(theme.border)
                .bg(theme.background)
                .cursor_pointer()
                .hover(|card| card.bg(theme.list_hover))
                .child(div().text_sm().font_medium().truncate().child(text(&prompt, "title")))
                .child(
                    div()
                        .text_xs()
                        .text_color(theme.muted_foreground)
                        .child(ui::clip(&text(&prompt, "content").replace('\n', " "), 110)),
                )
                .on_click(cx.listener(move |this, _, window, cx| this.start_from(&prompt, window, cx)))
        });
        h_flex().gap_3().flex_wrap().children(cards).into_any_element()
    }
}

impl Render for HomePage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let queens = self.queens(cx);
        let picker = queen_chips("pick-queen", &queens, self.picked.as_deref(), cx, |this: &mut Self, queen, _, cx| {
            this.picked = if this.picked.as_deref() == Some(queen.id.as_str()) { None } else { Some(queen.id.clone()) };
            this.error = None;
            cx.notify();
        });
        let empty = self.composer.read(cx).value().trim().is_empty();
        let send = Button::new("send")
            .small()
            .primary()
            .icon(IconName::Send)
            .label("Send")
            .on_click(cx.listener(|this, _, window, cx| this.send(window, cx)));
        let queen_cards = self.render_queens(&queens, cx);
        let quick_starts = (!self.prompts.is_empty()).then(|| self.render_prompts(cx));

        let theme = cx.theme().clone();
        let working = queens.iter().filter(|q| self.working.contains(&q.id)).count();
        let greeting = if self.name.is_empty() {
            "Hey there, what can I help you with?".to_string()
        } else {
            format!("Hey {}, what can I help you with?", self.name)
        };
        let counter = |value: usize, one: &str, many: &str, lit: bool| {
            h_flex()
                .gap_1()
                .text_xs()
                .text_color(if lit { theme.primary } else { theme.muted_foreground })
                .child(div().font_semibold().child(value.to_string()))
                .child(if value == 1 { one.to_string() } else { many.to_string() })
        };

        let composer = v_flex()
            .gap_3()
            .p_4()
            .rounded_xl()
            .border_1()
            .border_color(theme.border)
            .bg(theme.popover)
            .shadow_sm()
            .child(Textarea::new(&self.composer).appearance(false))
            .child(
                v_flex()
                    .gap_1p5()
                    .child(div().text_xs().text_color(theme.muted_foreground).child("Who do you want to talk to?"))
                    .child(if queens.is_empty() {
                        ui::muted("No queens yet.", &theme).into_any_element()
                    } else {
                        picker.into_any_element()
                    }),
            )
            .child(
                h_flex()
                    .gap_3()
                    .justify_between()
                    .child(match &self.error {
                        Some(e) => ui::error_line(e.clone(), &theme),
                        None => ui::muted("Enter sends; Shift+Enter starts a new line.", &theme).text_xs(),
                    })
                    .child(send.disabled(empty)),
            );

        let content = v_flex()
            .gap_8()
            .px_8()
            .py_8()
            .w_full()
            .max_w(px(880.))
            .mx_auto()
            .child(
                v_flex()
                    .gap_2()
                    .child(h_flex().gap_4().child(counter(queens.len(), "queen", "queens", false)).child(counter(
                        working,
                        "working now",
                        "working now",
                        working > 0,
                    )))
                    .child(div().text_2xl().font_semibold().child(greeting))
                    .child(ui::muted("Describe a task, pick a queen, and she'll take it from there.", &theme)),
            )
            .child(composer)
            .child(ui::section("Queens", &theme).child(if queens.is_empty() {
                ui::muted("No queens yet.", &theme).into_any_element()
            } else {
                queen_cards
            }))
            .when_some(quick_starts, |col, cards| col.child(ui::section("Your prompts", &theme).child(cards)));
        div().id("home-body").size_full().overflow_y_scroll().child(content)
    }
}
