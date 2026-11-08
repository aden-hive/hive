//! A colony: its chat with the queen in charge, and a side panel for its workers, plan,
//! schedules and data. Mirrors `frontend/src/pages/colony-chat.tsx` and `ColonyPanel.tsx`.

use std::time::{Duration, SystemTime, UNIX_EPOCH};

use gpui_kit::assets::IconName;
use gpui_kit::base::{Selectable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _, Theme};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use crate::api::{api, encode};
use crate::chat_view::{ChatEvent, ChatView, Target};
use crate::sentinel::SentinelPanel;
use crate::shell::{Page, Route};
use crate::{bg, plan, ui};

/// How often the open tab is re-read; the web panel polls at 2–5 s.
const PANEL_POLL: Duration = Duration::from_secs(3);
/// Rows shown from a data table, the web panel's page size.
const ROW_PAGE: usize = 100;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Tab {
    Workers,
    Plan,
    Schedules,
    Data,
    Alerts,
    Colony,
}

impl Tab {
    const ALL: [Tab; 6] = [Tab::Workers, Tab::Plan, Tab::Schedules, Tab::Data, Tab::Alerts, Tab::Colony];

    fn label(self) -> &'static str {
        match self {
            Tab::Workers => "Workers",
            Tab::Plan => "Plan",
            Tab::Schedules => "Schedules",
            Tab::Data => "Data",
            Tab::Alerts => "Alerts",
            Tab::Colony => "Colony",
        }
    }
}

type Loaded<T> = Option<Result<T, String>>;

pub struct ColonyView {
    name: String,
    chat: Entity<ChatView>,
    session_id: Option<String>,
    panel_open: bool,
    tab: Tab,
    workers: Loaded<Vec<Value>>,
    /// The worker whose transcript is open, and the transcript once read.
    worker_open: Option<(String, Loaded<Vec<Value>>)>,
    plan: Loaded<Value>,
    triggers: Loaded<Vec<Value>>,
    tables: Loaded<Vec<Value>>,
    table: Option<String>,
    rows: Loaded<Value>,
    /// The new schedule's name, task, and "every N minutes" or cron.
    new_schedule: [Entity<InputState>; 3],
    rename_to: Entity<InputState>,
    sentinel: Entity<SentinelPanel>,
    /// Delete was pressed once; the second press deletes.
    confirm_delete: bool,
    error: Option<String>,
    tasks: Vec<Task<()>>,
}

impl EventEmitter<ChatEvent> for ColonyView {}

fn now_secs() -> f64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

/// "in 5m", "in 2h", from a number of seconds ahead.
fn ahead(seconds: f64) -> String {
    let s = seconds.max(0.0) as u64;
    match s {
        0..60 => "in under a minute".into(),
        60..3600 => format!("in {}m", s / 60),
        3600..86400 => format!("in {}h {}m", s / 3600, s % 3600 / 60),
        _ => format!("in {}d", s / 86400),
    }
}

/// A schedule's name, or what its timer says when it has none.
fn schedule_label(trigger: &Value) -> String {
    let name = trigger["name"].as_str().unwrap_or_default();
    if !name.is_empty() && trigger["trigger_id"].as_str() != Some(name) {
        return name.to_string();
    }
    let config = &trigger["trigger_config"];
    if let Some(minutes) = config["interval_minutes"].as_f64() {
        return if minutes >= 60.0 && minutes % 60.0 == 0.0 {
            format!("Every {}h", minutes / 60.0)
        } else {
            format!("Every {minutes}m")
        };
    }
    config["cron"].as_str().map(|c| format!("cron {c} (UTC)")).unwrap_or_else(|| name.to_string())
}

fn text(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

impl ColonyView {
    pub fn new(name: String, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let chat = cx.new(|cx| ChatView::new(Target::Colony(name.clone()), window, cx));
        cx.subscribe_in(&chat, window, |this, _, event: &ChatEvent, _, cx| match event {
            ChatEvent::Session(id) => {
                this.session_id = Some(id.clone());
                this.reload(cx);
            }
            ChatEvent::TogglePanel => {
                this.panel_open = !this.panel_open;
                let open = this.panel_open;
                this.chat.update(cx, |chat, cx| chat.set_panel_open(open, cx));
                this.reload(cx);
            }
            ChatEvent::Go(route) => cx.emit(ChatEvent::Go(route.clone())),
            ChatEvent::ColonyChanged { forget, go } => {
                cx.emit(ChatEvent::ColonyChanged { forget: forget.clone(), go: go.clone() })
            }
        })
        .detach();
        let rename_to = cx.new(|cx| InputState::new(window, cx).placeholder("new_name").default_value(name.clone()));
        let field = |hint: &'static str, window: &mut Window, cx: &mut Context<Self>| {
            cx.new(|cx| InputState::new(window, cx).placeholder(hint))
        };
        let new_schedule = [
            field("Name, e.g. Morning digest", window, cx),
            field("What the queen should do each time", window, cx),
            field("Every N minutes, or a cron line (UTC)", window, cx),
        ];
        let sentinel = cx.new(|cx| SentinelPanel::new(name.clone(), window, cx));
        let mut view = Self {
            name,
            chat,
            session_id: None,
            panel_open: false,
            tab: Tab::Workers,
            workers: None,
            worker_open: None,
            plan: None,
            triggers: None,
            tables: None,
            table: None,
            rows: None,
            new_schedule,
            rename_to,
            sentinel,
            confirm_delete: false,
            error: None,
            tasks: Vec::new(),
        };
        view.poll(cx);
        view
    }

    /// Re-read the open tab every few seconds while the panel shows.
    fn poll(&mut self, cx: &mut Context<Self>) {
        self.tasks.push(cx.spawn(async move |this, cx| {
            loop {
                cx.background_executor().timer(PANEL_POLL).await;
                if this
                    .update(cx, |view, cx| {
                        if view.panel_open {
                            view.reload(cx)
                        }
                    })
                    .is_err()
                {
                    break;
                }
            }
        }));
    }

    fn reload(&mut self, cx: &mut Context<Self>) {
        if !self.panel_open {
            return;
        }
        let api = api(cx);
        let colony = self.name.clone();
        match self.tab {
            Tab::Workers => {
                let Some(sid) = self.session_id.clone() else { return };
                self.tasks.push(bg::spawn(
                    cx,
                    move || api.get(&format!("/sessions/{sid}/workers")),
                    |this: &mut Self, got, _| {
                        this.workers = Some(
                            got.map(|b| b["workers"].as_array().cloned().unwrap_or_default())
                                .map_err(|e| e.to_string()),
                        );
                    },
                ));
            }
            Tab::Plan => {
                let Some(sid) = self.session_id.clone() else { return };
                self.tasks.push(bg::spawn(
                    cx,
                    move || plan::load(&api, &sid),
                    |this: &mut Self, got, _| this.plan = Some(got.map_err(|e| e.to_string())),
                ));
            }
            Tab::Schedules => {
                let Some(sid) = self.session_id.clone() else { return };
                self.tasks.push(bg::spawn(
                    cx,
                    move || api.get(&format!("/sessions/{sid}/triggers")),
                    |this: &mut Self, got, _| {
                        this.triggers = Some(
                            got.map(|b| b["triggers"].as_array().cloned().unwrap_or_default())
                                .map_err(|e| e.to_string()),
                        );
                    },
                ));
            }
            Tab::Colony | Tab::Alerts => {}
            Tab::Data => {
                let table = self.table.clone();
                self.tasks.push(bg::spawn(
                    cx,
                    move || {
                        let tables = api.get(&format!("/colonies/{colony}/data/tables"))?["tables"]
                            .as_array()
                            .cloned()
                            .unwrap_or_default();
                        let rows = match table {
                            Some(t) => Some(api.get(&format!(
                                "/colonies/{colony}/data/tables/{}/rows?limit={ROW_PAGE}",
                                encode(&t)
                            ))?),
                            None => None,
                        };
                        anyhow::Ok((tables, rows))
                    },
                    |this: &mut Self, got, _| match got {
                        Ok((tables, rows)) => {
                            this.tables = Some(Ok(tables));
                            if let Some(rows) = rows {
                                this.rows = Some(Ok(rows));
                            }
                        }
                        Err(e) => this.tables = Some(Err(e.to_string())),
                    },
                ));
            }
        }
    }

    /// Run a write against the colony's session, then re-read the tab.
    fn act(
        &mut self,
        work: impl FnOnce(crate::api::Api, String) -> anyhow::Result<Value> + Send + 'static,
        cx: &mut Context<Self>,
    ) {
        let Some(sid) = self.session_id.clone() else { return };
        let api = api(cx);
        self.error = None;
        self.tasks.push(bg::spawn(
            cx,
            move || work(api, sid),
            |this: &mut Self, done, cx| match done {
                Ok(_) => this.reload(cx),
                Err(e) => this.error = Some(e.to_string()),
            },
        ));
    }

    fn open_worker(&mut self, worker_id: String, cx: &mut Context<Self>) {
        if self.worker_open.as_ref().is_some_and(|(id, _)| *id == worker_id) {
            self.worker_open = None;
            cx.notify();
            return;
        }
        let Some(sid) = self.session_id.clone() else { return };
        self.worker_open = Some((worker_id.clone(), None));
        let api = api(cx);
        let id = worker_id.clone();
        self.tasks.push(bg::spawn(
            cx,
            move || api.get(&format!("/sessions/{sid}/workers/{id}/conversation")),
            move |this: &mut Self, got, _| {
                if let Some((open, transcript)) = this.worker_open.as_mut()
                    && *open == worker_id
                {
                    *transcript = Some(
                        got.map(|b| b["messages"].as_array().cloned().unwrap_or_default()).map_err(|e| e.to_string()),
                    );
                }
            },
        ));
        cx.notify();
    }

    fn add_schedule(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let [name, task, timing] = self.new_schedule.clone();
        let (name_v, task_v, timing_v) = (
            name.read(cx).value().trim().to_string(),
            task.read(cx).value().trim().to_string(),
            timing.read(cx).value().trim().to_string(),
        );
        if name_v.is_empty() || task_v.is_empty() || timing_v.is_empty() {
            self.error = Some("A schedule needs a name, a task and when to run.".into());
            cx.notify();
            return;
        }
        // A bare number is an interval; anything else is taken as cron, which the server checks.
        let config = match timing_v.parse::<u32>() {
            Ok(minutes) if minutes > 0 => json!({ "interval_minutes": minutes }),
            _ => json!({ "cron": timing_v }),
        };
        for field in [name, task, timing] {
            field.update(cx, |s, cx| s.set_value("", window, cx));
        }
        self.act(
            move |api, sid| {
                api.post(
                    &format!("/sessions/{sid}/triggers"),
                    json!({ "name": name_v, "task": task_v, "trigger_type": "timer", "trigger_config": config }),
                )
            },
            cx,
        );
    }

    fn rename(&mut self, cx: &mut Context<Self>) {
        let new_name = self.rename_to.read(cx).value().trim().to_string();
        if new_name.is_empty()
            || new_name == self.name
            || !new_name.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
        {
            self.error = Some("A colony name uses lowercase letters, digits and _ only.".into());
            cx.notify();
            return;
        }
        let (api, old) = (api(cx), self.name.clone());
        self.tasks.push(bg::spawn(
            cx,
            move || api.post(&format!("/colonies/{old}/rename"), json!({ "new_name": new_name })),
            |this: &mut Self, renamed, cx| match renamed {
                Ok(body) => {
                    let new_name = body["new_name"].as_str().unwrap_or_default().to_string();
                    cx.emit(ChatEvent::ColonyChanged { forget: this.name.clone(), go: Route::Colony(new_name) });
                }
                Err(e) => this.error = Some(e.to_string()),
            },
        ));
    }

    fn delete(&mut self, cx: &mut Context<Self>) {
        if !self.confirm_delete {
            self.confirm_delete = true;
            cx.notify();
            return;
        }
        let (api, name) = (api(cx), self.name.clone());
        // Without `purge` the server keeps the files, as the web's default does.
        self.tasks.push(bg::spawn(
            cx,
            move || api.delete(&format!("/colonies/{name}")),
            |this: &mut Self, deleted, cx| match deleted {
                Ok(_) => cx.emit(ChatEvent::ColonyChanged { forget: this.name.clone(), go: Route::Page(Page::Home) }),
                Err(e) => {
                    this.confirm_delete = false;
                    this.error = Some(e.to_string());
                }
            },
        ));
    }

    fn render_colony(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        v_flex()
            .gap_4()
            .child(
                v_flex()
                    .gap_2()
                    .child(div().text_sm().font_medium().child("Rename"))
                    .child(
                        div()
                            .text_xs()
                            .text_color(theme.muted_foreground)
                            .child("Lowercase letters, digits and _. Sessions using the old name stop."),
                    )
                    .child(
                        h_flex().gap_2().child(div().flex_1().child(Input::new(&self.rename_to).small())).child(
                            Button::new("rename")
                                .small()
                                .outline()
                                .label("Rename")
                                .on_click(cx.listener(|this, _, _, cx| this.rename(cx))),
                        ),
                    ),
            )
            .child(
                v_flex()
                    .gap_2()
                    .child(div().text_sm().font_medium().child("Delete"))
                    .child(
                        div()
                            .text_xs()
                            .text_color(theme.muted_foreground)
                            .child("Hides the colony and stops its sessions. Its files stay on disk."),
                    )
                    .child(
                        h_flex().child(
                            Button::new("delete-colony")
                                .small()
                                .outline()
                                .when(self.confirm_delete, |b| b.danger().label("Delete this colony"))
                                .when(!self.confirm_delete, |b| b.icon(IconName::Trash).label("Delete"))
                                .on_click(cx.listener(|this, _, _, cx| this.delete(cx))),
                        ),
                    ),
            )
            .into_any_element()
    }

    fn render_tabs(&self, cx: &mut Context<Self>) -> AnyElement {
        h_flex()
            .gap_1()
            .px_3()
            .py_2()
            .children(Tab::ALL.iter().map(|&tab| {
                Button::new(tab.label()).small().ghost().label(tab.label()).selected(self.tab == tab).on_click(
                    cx.listener(move |this, _, _, cx| {
                        this.tab = tab;
                        this.error = None;
                        this.confirm_delete = false;
                        this.reload(cx);
                        cx.notify();
                    }),
                )
            }))
            .into_any_element()
    }

    fn render_workers(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let workers = match &self.workers {
            None => return Spinner::new().small().into_any_element(),
            Some(Err(e)) => return ui::error_line(e.clone(), &theme).into_any_element(),
            Some(Ok(w)) => w.clone(),
        };
        if workers.is_empty() {
            return ui::muted("No workers yet. They show here when the queen starts them.", &theme).into_any_element();
        }
        let active = |w: &Value| matches!(w["status"].as_str(), Some("pending" | "running" | "queued"));
        let mut sorted = workers;
        sorted.sort_by(|a, b| {
            b["started_at"].as_f64().unwrap_or(0.0).total_cmp(&a["started_at"].as_f64().unwrap_or(0.0))
        });
        let any_active = sorted.iter().any(active);
        let mut col = v_flex().gap_2();
        if any_active {
            col = col.child(h_flex().justify_end().child(
                Button::new("stop-all").small().outline().label("Stop all workers").on_click(cx.listener(
                    |this, _, _, cx| {
                        this.act(|api, sid| api.post(&format!("/sessions/{sid}/workers/stop-all"), json!({})), cx)
                    },
                )),
            ));
        }
        for (ix, w) in sorted.iter().enumerate() {
            let id = text(&w["worker_id"]);
            let status = text(&w["status"]);
            let running = active(w);
            let goal = Some(text(&w["goal"])).filter(|g| !g.is_empty()).unwrap_or_else(|| text(&w["task"]));
            let mut facts = Vec::new();
            if let Some(t) = w["started_at"].as_f64() {
                facts.push(ui::ago(t));
            }
            if let Some(s) = w["result"]["duration_seconds"].as_f64() {
                facts.push(format!("{s:.0}s"));
            }
            if let Some(t) = w["result"]["tokens_used"].as_i64() {
                facts.push(format!("{t} tokens"));
            }
            if let Some(total) = w["task_summary"]["total"].as_i64().filter(|t| *t > 0) {
                facts.push(format!("{}/{total} tasks", w["task_summary"]["completed"].as_i64().unwrap_or(0)));
            }
            let color = match status.as_str() {
                "completed" | "done" => theme.success,
                "failed" => theme.danger,
                _ if running => theme.warning,
                _ => theme.muted_foreground,
            };
            let open = self.worker_open.as_ref().filter(|(open, _)| *open == id);
            let short: String = id.chars().take(8).collect();
            let (click_id, stop_id) = (id.clone(), id.clone());
            let mut card = v_flex()
                .id(("worker", ix))
                .gap_1()
                .p_3()
                .rounded_lg()
                .border_1()
                .border_color(theme.border)
                .cursor_pointer()
                .on_click(cx.listener(move |this, _, _, cx| this.open_worker(click_id.clone(), cx)))
                .child(
                    h_flex()
                        .justify_between()
                        .child(
                            h_flex()
                                .gap_2()
                                .child(div().text_sm().font_medium().child(format!("Worker {short}")))
                                .child(
                                    h_flex().gap_1().text_xs().text_color(color).child(ui::dot(color)).child(status),
                                ),
                        )
                        .when(running, |row| {
                            row.child(Button::new(("stop-worker", ix)).xsmall().ghost().label("Stop").on_click(
                                cx.listener(move |this, _, _, cx| {
                                    let id = stop_id.clone();
                                    this.act(
                                        move |api, sid| {
                                            api.post(&format!("/sessions/{sid}/workers/{id}/stop"), json!({}))
                                        },
                                        cx,
                                    )
                                }),
                            ))
                        }),
                )
                .when(!goal.is_empty(), |c| c.child(div().text_sm().child(ui::clip(&goal, 240))))
                .child(div().text_xs().text_color(theme.muted_foreground).child(facts.join(" · ")))
                .when_some(w["result"]["summary"].as_str().filter(|s| !s.is_empty()).map(str::to_string), |c, s| {
                    c.child(div().text_sm().text_color(theme.muted_foreground).child(ui::clip(&s, 400)))
                })
                .when_some(w["result"]["error"].as_str().filter(|s| !s.is_empty()).map(str::to_string), |c, e| {
                    c.child(div().text_xs().text_color(theme.danger).child(e))
                });
            if let Some((_, transcript)) = open {
                card = card.child(render_transcript(transcript, &theme));
            }
            col = col.child(card);
        }
        col.into_any_element()
    }

    fn render_plan(&self, cx: &mut Context<Self>) -> AnyElement {
        let done = match &self.plan {
            Some(Ok(p)) => plan::visible(p).iter().filter(|t| t["status"] == "completed").count(),
            _ => 0,
        };
        let clear = cx.listener(|this, _, _, cx| {
            this.act(|api, sid| api.post(&format!("/sessions/{sid}/tasks/clear-completed"), json!({})), cx)
        });
        v_flex()
            .gap_2()
            .child(plan::render(&self.plan, cx.theme()))
            .when(done > 0, |c| {
                c.child(h_flex().justify_end().child(
                    Button::new("clear-done").small().ghost().label(format!("Clear done ({done})")).on_click(clear),
                ))
            })
            .into_any_element()
    }

    fn render_schedules(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let triggers = match &self.triggers {
            None => return Spinner::new().small().into_any_element(),
            Some(Err(e)) => return ui::error_line(e.clone(), &theme).into_any_element(),
            Some(Ok(t)) => t.clone(),
        };
        let [name, task, timing] = &self.new_schedule;
        let mut col = v_flex().gap_2();
        if triggers.is_empty() {
            col = col.child(ui::muted("No schedules yet.", &theme));
        }
        for (ix, t) in triggers.iter().enumerate() {
            let id = text(&t["trigger_id"]);
            let enabled = t["enabled"].as_bool().unwrap_or(false);
            let config = &t["trigger_config"];
            let next =
                config["next_fire_at"].as_f64().map(|ms| ms / 1000.0 - now_secs()).or(config["next_fire_in"].as_f64());
            let mut facts = Vec::new();
            if enabled && let Some(next) = next {
                facts.push(ahead(next));
            }
            if let Some(n) = config["fire_count"].as_i64().filter(|n| *n > 0) {
                facts.push(format!("fired {n}×"));
            }
            if let Some(last) = config["last_fired_at"].as_f64() {
                facts.push(format!("last {}", ui::ago(last / 1000.0)));
            }
            let (toggle_id, run_id) = (id.clone(), id.clone());
            col = col.child(
                v_flex()
                    .gap_1()
                    .p_3()
                    .rounded_lg()
                    .border_1()
                    .border_color(theme.border)
                    .child(
                        h_flex()
                            .justify_between()
                            .child(
                                h_flex()
                                    .gap_2()
                                    .child(Icon::new(IconName::Clock).small().text_color(if enabled {
                                        theme.success
                                    } else {
                                        theme.muted_foreground
                                    }))
                                    .child(div().text_sm().font_medium().child(schedule_label(t))),
                            )
                            .child(
                                h_flex()
                                    .gap_1()
                                    .child(Button::new(("run", ix)).xsmall().ghost().label("Run now").on_click(
                                        cx.listener(move |this, _, _, cx| {
                                            let id = run_id.clone();
                                            this.act(
                                                move |api, sid| {
                                                    api.post(
                                                        &format!("/sessions/{sid}/triggers/{}/run", encode(&id)),
                                                        json!({}),
                                                    )
                                                },
                                                cx,
                                            )
                                        }),
                                    ))
                                    .child(
                                        Button::new(("toggle", ix))
                                            .xsmall()
                                            .outline()
                                            .label(if enabled { "Pause" } else { "Resume" })
                                            .on_click(cx.listener(move |this, _, _, cx| {
                                                let (id, verb) = (
                                                    toggle_id.clone(),
                                                    if enabled { "deactivate" } else { "activate" },
                                                );
                                                this.act(
                                                    move |api, sid| {
                                                        api.post(
                                                            &format!("/sessions/{sid}/triggers/{}/{verb}", encode(&id)),
                                                            json!({}),
                                                        )
                                                    },
                                                    cx,
                                                )
                                            })),
                                    ),
                            ),
                    )
                    .when_some(t["task"].as_str().filter(|s| !s.is_empty()).map(str::to_string), |c, task| {
                        c.child(div().text_sm().text_color(theme.muted_foreground).child(ui::clip(&task, 300)))
                    })
                    .when(!facts.is_empty(), |c| {
                        c.child(div().text_xs().text_color(theme.muted_foreground).child(facts.join(" · ")))
                    }),
            );
        }
        col.child(
            v_flex()
                .gap_2()
                .mt_2()
                .p_3()
                .rounded_lg()
                .bg(theme.sidebar)
                .child(div().text_sm().font_medium().child("New schedule"))
                .child(Input::new(name).small())
                .child(Input::new(task).small())
                .child(Input::new(timing).small())
                .child(
                    div()
                        .text_xs()
                        .text_color(theme.muted_foreground)
                        .child("Removing a schedule is up to the queen; ask her in the chat."),
                )
                .child(
                    h_flex().justify_end().child(
                        Button::new("add-schedule")
                            .small()
                            .primary()
                            .icon(IconName::Plus)
                            .label("Add")
                            .on_click(cx.listener(|this, _, window, cx| this.add_schedule(window, cx))),
                    ),
                ),
        )
        .into_any_element()
    }

    fn render_data(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let tables = match &self.tables {
            None => return Spinner::new().small().into_any_element(),
            Some(Err(e)) => return ui::error_line(e.clone(), &theme).into_any_element(),
            Some(Ok(t)) => t.clone(),
        };
        if tables.is_empty() {
            return ui::muted("No data yet. Tables the colony keeps show here.", &theme).into_any_element();
        }
        let picker = h_flex().gap_1().flex_wrap().children(tables.iter().enumerate().map(|(ix, t)| {
            let name = text(&t["name"]);
            let selected = self.table.as_deref() == Some(name.as_str());
            Button::new(("table", ix))
                .small()
                .ghost()
                .selected(selected)
                .label(format!("{name} ({})", text(&t["row_count"])))
                .on_click(cx.listener(move |this, _, _, cx| {
                    this.table = Some(name.clone());
                    this.rows = None;
                    this.reload(cx);
                    cx.notify();
                }))
        }));
        let grid = match (&self.table, &self.rows) {
            (None, _) => ui::muted("Pick a table.", &theme).into_any_element(),
            (Some(_), None) => Spinner::new().small().into_any_element(),
            (Some(_), Some(Err(e))) => ui::error_line(e.clone(), &theme).into_any_element(),
            (Some(_), Some(Ok(rows))) => render_grid(rows, &theme),
        };
        v_flex().gap_3().child(picker).child(grid).into_any_element()
    }
}

/// A worker's conversation, as `GET …/workers/{id}/conversation` returns it.
fn render_transcript(transcript: &Loaded<Vec<Value>>, theme: &Theme) -> AnyElement {
    let messages = match transcript {
        None => return Spinner::new().small().into_any_element(),
        Some(Err(e)) => return ui::error_line(e.clone(), theme).into_any_element(),
        Some(Ok(m)) => m,
    };
    v_flex()
        .mt_2()
        .gap_2()
        .p_2()
        .rounded_md()
        .bg(theme.muted)
        .children(messages.iter().map(|m| {
            let calls: Vec<String> = m["tool_calls"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|c| c["name"].as_str().map(str::to_string))
                .collect();
            v_flex()
                .gap_0p5()
                .child(div().text_xs().font_semibold().text_color(theme.muted_foreground).child(text(&m["role"])))
                .when(!text(&m["content"]).is_empty(), |c| {
                    c.child(div().text_xs().child(ui::clip(&text(&m["content"]), 1200)))
                })
                .when(!calls.is_empty(), |c| {
                    c.child(div().text_xs().text_color(theme.muted_foreground).child(format!("→ {}", calls.join(", "))))
                })
        }))
        .into_any_element()
}

/// A table's rows in fixed-width columns that scroll sideways.
fn render_grid(rows: &Value, theme: &Theme) -> AnyElement {
    const CELL: f32 = 160.;
    let columns: Vec<String> = rows["columns"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|c| c["name"].as_str().map(str::to_string).unwrap_or_else(|| text(c)))
        .collect();
    let cell = |s: String| div().w(px(CELL)).flex_shrink_0().px_2().py_1().truncate().child(s);
    let header = h_flex()
        .border_b_1()
        .border_color(theme.border)
        .text_xs()
        .font_semibold()
        .children(columns.iter().map(|c| cell(c.clone())));
    let body = rows["rows"].as_array().cloned().unwrap_or_default().into_iter().map(|row| {
        h_flex()
            .text_xs()
            .border_b_1()
            .border_color(theme.border)
            .children(columns.iter().map(|c| cell(ui::clip(&text(&row[c]), 120))))
    });
    let total = rows["total"].as_i64().unwrap_or(0);
    v_flex()
        .gap_1()
        .child(div().id("grid").overflow_x_scroll().child(v_flex().child(header).children(body)))
        .when(total as usize > ROW_PAGE, |c| {
            c.child(
                div()
                    .text_xs()
                    .text_color(theme.muted_foreground)
                    .child(format!("Showing the first {ROW_PAGE} of {total} rows.")),
            )
        })
        .into_any_element()
}

impl Render for ColonyView {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let panel = self.panel_open.then(|| {
            let tabs = self.render_tabs(cx);
            let body = match self.tab {
                Tab::Workers => self.render_workers(cx),
                Tab::Plan => self.render_plan(cx),
                Tab::Schedules => self.render_schedules(cx),
                Tab::Data => self.render_data(cx),
                Tab::Alerts => self.sentinel.clone().into_any_element(),
                Tab::Colony => self.render_colony(cx),
            };
            let theme = cx.theme();
            v_flex()
                .w(px(440.))
                .h_full()
                .flex_shrink_0()
                .border_l_1()
                .border_color(theme.border)
                .bg(theme.background)
                .child(tabs)
                .when_some(self.error.clone(), |c, e| c.child(div().px_3().child(ui::error_line(e, theme))))
                .when(self.session_id.is_none(), |c| {
                    c.child(div().px_3().child(ui::muted("Waiting for the colony's session…", theme)))
                })
                .child(div().id("panel").flex_1().min_h_0().overflow_y_scroll().px_3().pb_4().child(body))
        });
        h_flex().size_full().child(div().flex_1().h_full().min_w_0().child(self.chat.clone())).children(panel)
    }
}

#[cfg(test)]
mod tests {
    // Not `super::*`: GPUI's own `test` macro would shadow the standard one.
    use super::schedule_label;
    use serde_json::json;

    #[test]
    fn names_a_schedule_by_its_name_else_its_timer() {
        assert_eq!(schedule_label(&json!({ "trigger_id": "digest", "name": "Morning digest" })), "Morning digest");
        assert_eq!(
            schedule_label(&json!({ "trigger_id": "t1", "name": "t1", "trigger_config": { "interval_minutes": 120 } })),
            "Every 2h"
        );
        assert_eq!(
            schedule_label(&json!({ "trigger_id": "t2", "name": "t2", "trigger_config": { "interval_minutes": 45 } })),
            "Every 45m"
        );
        assert_eq!(
            schedule_label(&json!({ "trigger_id": "t3", "name": "t3", "trigger_config": { "cron": "0 9 * * 1" } })),
            "cron 0 9 * * 1 (UTC)"
        );
    }
}
