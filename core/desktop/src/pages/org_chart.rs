//! The team as an org chart: you at the top, the queens below with the colonies they lead, and
//! the positions to add, remove and restore. Mirrors `frontend/src/pages/org-chart.tsx` and
//! `components/PositionCatalog.tsx`, laid out in place rather than on a canvas.

use std::collections::{HashMap, HashSet};

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, Selectable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState, Textarea, TextareaState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use super::text;
use crate::api::{Queen, SessionSummary, api};
use crate::shell::{Route, Shell};
use crate::{avatars, bg, ui};

/// Where an error from loading the page, or from the new-position form, shows.
const LOAD: &str = "load";
const NEW: &str = "new";

struct NewPosition {
    position: Entity<InputState>,
    name: Entity<InputState>,
    persona: Entity<TextareaState>,
}

/// What the page reads besides the queens, which come from the sidebar's list.
struct Loaded {
    /// Each queen's colonies as (directory name, display name), by queen id.
    colonies: HashMap<String, Vec<(String, String)>>,
    /// Queens with a chat running now.
    live: HashSet<String>,
    removed: Vec<Value>,
    user_name: String,
}

pub struct OrgChartPage {
    shell: WeakEntity<Shell>,
    loaded: Option<Loaded>,
    form: Option<NewPosition>,
    /// The queen whose Remove was clicked once; a second click removes her.
    confirm_remove: Option<String>,
    /// The queen (or `NEW`) being written, while it is.
    busy: Option<String>,
    /// What failed, and where: a queen id, `NEW` or `LOAD`.
    error: Option<(String, String)>,
    tasks: Vec<Task<()>>,
}

fn counted(n: usize, one: &str, many: &str) -> String {
    format!("{n} {}", if n == 1 { one } else { many })
}

/// The last segment of a path, `/`- or `\`-separated: a colony's directory name.
fn last_segment(path: &str) -> &str {
    let path = path.trim_end_matches(['/', '\\']);
    path.rsplit(['/', '\\']).next().unwrap_or(path)
}

/// Who leads each colony `GET /discover` lists, as the web's colony list decides it: her running
/// chat in it, else her latest chat there, else the queen it was made by.
fn colonies_by_queen(
    discover: &Value,
    live: &[Value],
    history: &[SessionSummary],
) -> HashMap<String, Vec<(String, String)>> {
    let mut lead: HashMap<String, String> = HashMap::new();
    for s in live {
        let (path, queen) = (text(s, "agent_path"), text(s, "queen_id"));
        if !path.is_empty() && !queen.is_empty() {
            lead.entry(last_segment(&path).to_string()).or_insert(queen);
        }
    }
    for s in history {
        if let (Some(path), Some(queen)) = (&s.agent_path, &s.queen_id) {
            lead.entry(last_segment(path).to_string()).or_insert_with(|| queen.clone());
        }
    }
    let mut out: HashMap<String, Vec<(String, String)>> = HashMap::new();
    let mut seen = HashSet::new();
    for (category, entries) in discover.as_object().into_iter().flatten() {
        if category == "Framework" {
            continue;
        }
        for entry in entries.as_array().into_iter().flatten() {
            let dir = last_segment(&text(entry, "path")).to_string();
            if dir.is_empty() || !seen.insert(dir.clone()) {
                continue;
            }
            let queen = lead.get(&dir).cloned().unwrap_or_else(|| text(&entry["workers"][0], "queen_name"));
            if queen.is_empty() {
                continue;
            }
            let name = Some(text(entry, "name")).filter(|n| !n.is_empty()).unwrap_or_else(|| dir.clone());
            out.entry(queen).or_default().push((dir, name));
        }
    }
    out
}

impl OrgChartPage {
    pub fn new(shell: WeakEntity<Shell>, _window: &mut Window, cx: &mut Context<Self>) -> Self {
        // The queens are the sidebar's list, so redraw whenever it's reloaded.
        if let Some(shell) = shell.upgrade() {
            cx.observe(&shell, |_, _, cx| cx.notify()).detach();
        }
        let mut page =
            Self { shell, loaded: None, form: None, confirm_remove: None, busy: None, error: None, tasks: Vec::new() };
        page.load(cx);
        page
    }

    fn load(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let discover = api.get("/discover")?;
                let live = api
                    .get("/sessions")
                    .map(|b| b["sessions"].as_array().cloned().unwrap_or_default())
                    .unwrap_or_default();
                let history = api.sessions().unwrap_or_default();
                // Nothing to offer back, or no name for you, is no reason to fail the chart.
                let removed = api
                    .get("/queen/removed")
                    .map(|b| b["queens"].as_array().cloned().unwrap_or_default())
                    .unwrap_or_default();
                let user_name = api.get("/config/profile").map(|b| text(&b, "displayName")).unwrap_or_default();
                Ok(Loaded {
                    colonies: colonies_by_queen(&discover, &live, &history),
                    live: live.iter().map(|s| text(s, "queen_id")).filter(|q| !q.is_empty()).collect(),
                    removed,
                    user_name,
                })
            },
            |this: &mut Self, loaded, _| match loaded {
                Ok(loaded) => {
                    this.loaded = Some(loaded);
                    if this.error.as_ref().is_some_and(|(at, _)| at == LOAD) {
                        this.error = None;
                    }
                }
                Err(e) => this.error = Some((LOAD.into(), format!("Couldn't load the colonies: {e}"))),
            },
        ));
    }

    fn open_form(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.form.take().is_some() {
            cx.notify();
            return;
        }
        let position = cx.new(|cx| InputState::new(window, cx).placeholder("e.g. Head of Testing, Illustrator"));
        let name = cx.new(|cx| InputState::new(window, cx).placeholder("Who holds it, e.g. Mira"));
        let persona = cx.new(|cx| {
            TextareaState::new(window, cx)
                .auto_grow(3, 10)
                .placeholder("Voice, temperament, duties… (her profile page can take it from here)")
        });
        // Create is offered only once both are filled in.
        cx.observe(&position, |_, _, cx| cx.notify()).detach();
        cx.observe(&name, |_, _, cx| cx.notify()).detach();
        position.update(cx, |s, cx| s.focus(window, cx));
        self.form = Some(NewPosition { position, name, persona });
        if self.error.as_ref().is_some_and(|(at, _)| at == NEW) {
            self.error = None;
        }
        cx.notify();
    }

    fn create(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(form) = &self.form else { return };
        let title = form.position.read(cx).value().trim().to_string();
        let name = form.name.read(cx).value().trim().to_string();
        let persona = form.persona.read(cx).value().trim().to_string();
        if title.is_empty() || name.is_empty() {
            return;
        }
        self.busy = Some(NEW.into());
        self.error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || {
                let mut body = json!({ "name": name, "title": title });
                if !persona.is_empty() {
                    body["persona"] = json!(persona);
                }
                api.post("/queen/create", body)
            },
            |this: &mut Self, created, window, cx| {
                this.busy = None;
                match created {
                    Ok(body) => {
                        this.form = None;
                        let id = text(&body["queen"], "id");
                        this.shell
                            .update(cx, |shell, cx| {
                                shell.refresh_queens(window, cx);
                                shell.go(Route::Profile(id), window, cx);
                            })
                            .ok();
                    }
                    Err(e) => this.error = Some((NEW.into(), e.to_string())),
                }
            },
        ));
        cx.notify();
    }

    fn remove(&mut self, id: String, window: &mut Window, cx: &mut Context<Self>) {
        if self.confirm_remove.as_deref() != Some(id.as_str()) {
            self.confirm_remove = Some(id);
            cx.notify();
            return;
        }
        self.confirm_remove = None;
        let path = format!("/queen/{id}/remove");
        self.change(id, path, window, cx);
    }

    /// Remove or restore her, then read the removed list and the sidebar's queens again.
    fn change(&mut self, id: String, path: String, window: &mut Window, cx: &mut Context<Self>) {
        self.busy = Some(id.clone());
        self.error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || {
                api.post(&path, json!({}))?;
                api.get("/queen/removed")
            },
            move |this: &mut Self, done, window, cx| {
                this.busy = None;
                match done {
                    Ok(removed) => {
                        if let Some(loaded) = this.loaded.as_mut() {
                            loaded.removed = removed["queens"].as_array().cloned().unwrap_or_default();
                        }
                        this.shell
                            .update(cx, |shell, cx| {
                                // A profile opened before shows her as she was; build it afresh next time.
                                shell.forget(&Route::Profile(id));
                                shell.refresh_queens(window, cx);
                            })
                            .ok();
                    }
                    Err(e) => this.error = Some((id, e.to_string())),
                }
            },
        ));
        cx.notify();
    }

    fn error_at(&self, at: &str) -> Option<String> {
        self.error.as_ref().filter(|(where_, _)| where_ == at).map(|(_, e)| e.clone())
    }

    fn render_form(&self, form: &NewPosition, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let ready = !form.position.read(cx).value().trim().is_empty() && !form.name.read(cx).value().trim().is_empty();
        let field = |label: &'static str| div().text_xs().text_color(theme.muted_foreground).child(label);
        v_flex()
            .gap_2()
            .p_4()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .max_w(px(560.))
            .child(div().text_sm().font_semibold().child("New position"))
            .child(field("Position"))
            .child(Input::new(&form.position).small())
            .child(field("Her name"))
            .child(Input::new(&form.name).small())
            .child(field("Persona (optional): free text that becomes her core traits"))
            .child(Textarea::new(&form.persona))
            .when_some(self.error_at(NEW), |col, e| col.child(ui::error_line(e, &theme)))
            .child(
                h_flex()
                    .gap_2()
                    .justify_end()
                    .child(Button::new("new-cancel").small().ghost().label("Cancel").on_click(cx.listener(
                        |this, _, _, cx| {
                            this.form = None;
                            cx.notify();
                        },
                    )))
                    .child(
                        Button::new("new-create")
                            .small()
                            .primary()
                            .label("Create")
                            .loading(self.busy.as_deref() == Some(NEW))
                            .disabled(!ready)
                            .on_click(cx.listener(|this, _, window, cx| this.create(window, cx))),
                    ),
            )
            .into_any_element()
    }

    fn render_queen(&self, ix: usize, queen: &Queen, picture: AnyElement, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let id = queen.id.clone();
        let colonies = self.loaded.as_ref().and_then(|l| l.colonies.get(&id)).cloned().unwrap_or_default();
        let live = self.loaded.as_ref().is_some_and(|l| l.live.contains(&id));
        let confirming = self.confirm_remove.as_deref() == Some(id.as_str());
        let busy = self.busy.as_deref() == Some(id.as_str());
        let profile_id = id.clone();
        let remove_id = id.clone();

        let tags = colonies.into_iter().enumerate().map(|(cix, (dir, name))| {
            h_flex()
                .id(SharedString::from(format!("colony-{ix}-{cix}")))
                .gap_1()
                .max_w_full()
                .px_2()
                .py_0p5()
                .rounded_md()
                .border_1()
                .border_color(theme.border)
                .bg(theme.muted)
                .text_xs()
                .cursor_pointer()
                .hover(|tag| tag.bg(theme.list_hover))
                .child(Icon::new(IconName::Hexagon).xsmall().text_color(theme.primary))
                .child(div().truncate().child(name))
                .on_click(cx.listener(move |this, _, window, cx| {
                    let route = Route::Colony(dir.clone());
                    this.shell.update(cx, |shell, cx| shell.go(route, window, cx)).ok();
                }))
        });
        let tags: Vec<_> = tags.collect();

        let footer = if confirming {
            v_flex()
                .gap_2()
                .child(
                    div()
                        .text_xs()
                        .text_color(theme.muted_foreground)
                        .child("Remove her position? Her chats and memory stay, so she can be restored."),
                )
                .child(
                    h_flex()
                        .gap_1()
                        .justify_center()
                        .child(
                            Button::new(("remove-yes", ix)).xsmall().danger().label("Remove").loading(busy).on_click(
                                cx.listener(move |this, _, window, cx| this.remove(remove_id.clone(), window, cx)),
                            ),
                        )
                        .child(Button::new(("remove-no", ix)).xsmall().ghost().label("Cancel").on_click(cx.listener(
                            |this, _, _, cx| {
                                this.confirm_remove = None;
                                cx.notify();
                            },
                        ))),
                )
                .into_any_element()
        } else {
            h_flex()
                .justify_center()
                .child(
                    Button::new(("remove", ix))
                        .xsmall()
                        .ghost()
                        .icon(IconName::UserMinus)
                        .label("Remove")
                        .loading(busy)
                        .on_click(cx.listener(move |this, _, window, cx| this.remove(remove_id.clone(), window, cx))),
                )
                .into_any_element()
        };

        v_flex()
            .w(px(208.))
            .gap_3()
            .p_3()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.background)
            .child(
                v_flex()
                    .id(("queen-card", ix))
                    .items_center()
                    .gap_1()
                    .p_2()
                    .rounded_md()
                    .cursor_pointer()
                    .hover(|area| area.bg(theme.list_hover))
                    .child(picture)
                    .child(
                        h_flex()
                            .gap_1p5()
                            .max_w_full()
                            .pt_1()
                            .when(live, |row| row.child(ui::dot(theme.success)))
                            .child(div().text_sm().font_semibold().truncate().child(queen.name.clone())),
                    )
                    .child(
                        div()
                            .text_xs()
                            .text_color(theme.muted_foreground)
                            .max_w_full()
                            .truncate()
                            .child(ui::role(&queen.title).to_string()),
                    )
                    .on_click(cx.listener(move |this, _, window, cx| {
                        let route = Route::Profile(profile_id.clone());
                        this.shell.update(cx, |shell, cx| shell.go(route, window, cx)).ok();
                    })),
            )
            .child(if tags.is_empty() {
                div()
                    .text_xs()
                    .text_color(theme.muted_foreground)
                    .text_center()
                    .child("No colonies yet")
                    .into_any_element()
            } else {
                h_flex().gap_1().flex_wrap().justify_center().children(tags).into_any_element()
            })
            .when_some(self.error_at(&id), |col, e| col.child(ui::error_line(e, &theme).text_xs()))
            .child(footer)
            .into_any_element()
    }

    fn render_removed(&self, cx: &mut Context<Self>) -> Option<AnyElement> {
        let removed = self.loaded.as_ref().map(|l| l.removed.clone()).unwrap_or_default();
        if removed.is_empty() {
            return None;
        }
        let theme = cx.theme().clone();
        let rows = removed.into_iter().enumerate().map(|(ix, q)| {
            let id = text(&q, "id");
            let name = Some(text(&q, "name")).filter(|n| !n.is_empty()).unwrap_or_else(|| id.clone());
            let title = Some(text(&q, "title")).filter(|t| !t.is_empty()).unwrap_or_else(|| name.clone());
            let busy = self.busy.as_deref() == Some(id.as_str());
            let error = self.error_at(&id);
            ui::card(&theme)
                .justify_between()
                .child(
                    v_flex()
                        .min_w_0()
                        .child(div().text_sm().font_medium().truncate().child(title))
                        .child(div().text_xs().text_color(theme.muted_foreground).truncate().child(name))
                        .when_some(error, |col, e| col.child(ui::error_line(e, &theme))),
                )
                .child(
                    Button::new(("restore", ix))
                        .small()
                        .outline()
                        .icon(IconName::ArchiveRestore)
                        .label("Restore")
                        .loading(busy)
                        .on_click(cx.listener(move |this, _, window, cx| {
                            let path = format!("/queen/{id}/restore");
                            this.change(id.clone(), path, window, cx);
                        })),
                )
        });
        Some(v_flex().gap_2().max_w(px(560.)).children(rows).into_any_element())
    }
}

impl Render for OrgChartPage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let queens: Vec<Queen> = self.shell.upgrade().map(|s| s.read(cx).queens().to_vec()).unwrap_or_default();
        let pictures: Vec<AnyElement> = queens.iter().map(|q| avatars::avatar(q, px(56.), cx)).collect();
        let theme = cx.theme().clone();
        let colony_count: usize = self.loaded.as_ref().map(|l| l.colonies.values().map(Vec::len).sum()).unwrap_or(0);
        let lede = format!(
            "Who reports to you, and the colonies each queen leads. {} · {}.",
            counted(queens.len(), "queen", "queens"),
            counted(colony_count, "colony", "colonies")
        );
        let (header, body) = ui::page("org-body", "Org chart", lede, &theme);
        let header = header.child(
            h_flex()
                .pt_2()
                .gap_2()
                .child(
                    Button::new("new-position")
                        .small()
                        .outline()
                        .icon(IconName::Plus)
                        .label("New position")
                        .selected(self.form.is_some())
                        .on_click(cx.listener(|this, _, window, cx| this.open_form(window, cx))),
                )
                .child(Button::new("refresh").small().ghost().icon(IconName::RefreshCw).label("Refresh").on_click(
                    cx.listener(|this, _, window, cx| {
                        this.load(cx);
                        this.shell.update(cx, |shell, cx| shell.refresh_queens(window, cx)).ok();
                    }),
                )),
        );

        let user_name = self.loaded.as_ref().map(|l| l.user_name.clone()).filter(|n| !n.trim().is_empty());
        let you = v_flex()
            .w(px(220.))
            .items_center()
            .gap_1()
            .p_4()
            .rounded_lg()
            .border_1()
            .border_color(theme.primary)
            .bg(theme.background)
            .child(match &user_name {
                Some(name) => ui::initial_avatar(name, px(48.), &theme).into_any_element(),
                None => div()
                    .size(px(48.))
                    .rounded_full()
                    .flex()
                    .items_center()
                    .justify_center()
                    .bg(theme.primary)
                    .text_color(theme.primary_foreground)
                    .child(Icon::new(IconName::User))
                    .into_any_element(),
            })
            .child(div().pt_1().text_sm().font_semibold().child(user_name.unwrap_or_else(|| "You".into())))
            .child(div().text_xs().text_color(theme.muted_foreground).child("CEO / Founder"));

        let cards: Vec<AnyElement> = queens
            .iter()
            .zip(pictures)
            .enumerate()
            .map(|(ix, (queen, picture))| self.render_queen(ix, queen, picture, cx))
            .collect();
        let team = if cards.is_empty() {
            ui::muted("No queens yet. Add a position to start your team.", &theme).p_6().into_any_element()
        } else {
            h_flex()
                .w_full()
                .flex_wrap()
                .justify_center()
                .items_start()
                .gap_4()
                .p_6()
                .rounded_xl()
                .border_1()
                .border_color(theme.border)
                .children(cards)
                .into_any_element()
        };

        let content = v_flex()
            .gap_6()
            .px_8()
            .py_6()
            .when_some(self.error_at(LOAD), |col, e| col.child(ui::error_line(e, &theme)))
            .when_some(self.form.as_ref().map(|f| self.render_form(f, cx)), |col, form| col.child(form))
            .child(
                v_flex()
                    .items_center()
                    .child(you)
                    // The line from you down to your team.
                    .child(div().w(px(1.)).h(px(28.)).bg(theme.border))
                    .child(if self.loaded.is_none() {
                        v_flex().items_center().p_6().child(Spinner::new()).into_any_element()
                    } else {
                        team
                    }),
            )
            .when_some(self.render_removed(cx), |col, removed| {
                col.child(ui::section("Removed positions", &theme).child(removed))
            });
        v_flex().size_full().child(header).child(body.child(content))
    }
}

#[cfg(test)]
mod tests {
    // Not `super::*`: that brings GPUI's own `test` attribute along.
    use super::{colonies_by_queen, last_segment};
    use serde_json::{Value, json};

    #[test]
    fn colony_dir_is_the_last_segment() {
        assert_eq!(last_segment("/home/ava/.hive/colonies/zed_watch"), "zed_watch");
        assert_eq!(last_segment("C:\\hive\\colonies\\ivy_notes\\"), "ivy_notes");
        assert_eq!(last_segment("solo"), "solo");
    }

    #[test]
    fn a_running_chat_decides_the_lead_before_the_maker() {
        let discover: Value = serde_json::from_str(
            r#"{
                "Framework": [{ "path": "/x/framework/demo", "name": "Demo", "workers": [{ "queen_name": "queen_ava" }] }],
                "Your Agents": [
                    { "path": "/x/colonies/zed_watch", "name": "Zed Watch", "workers": [{ "queen_name": "queen_ava" }] },
                    { "path": "/x/colonies/ivy_notes", "name": "", "workers": [{ "queen_name": "queen_ivy" }] },
                    { "path": "/x/colonies/lonely", "name": "Lonely", "workers": [] }
                ]
            }"#,
        )
        .unwrap();
        let live = vec![json!({ "agent_path": "/x/colonies/zed_watch", "queen_id": "queen_mira" })];
        let colonies = colonies_by_queen(&discover, &live, &[]);
        assert_eq!(colonies.get("queen_mira"), Some(&vec![("zed_watch".to_string(), "Zed Watch".to_string())]));
        assert_eq!(colonies.get("queen_ivy"), Some(&vec![("ivy_notes".to_string(), "ivy_notes".to_string())]));
        assert!(!colonies.contains_key("queen_ava"));
        assert_eq!(colonies.values().map(Vec::len).sum::<usize>(), 2);
    }
}
