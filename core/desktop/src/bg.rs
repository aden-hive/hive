//! Run a blocking API call off the UI thread and hand its result back to the view that asked.

use gpui_kit::*;

/// Run `work` on the background pool, then `done` on the view, which is redrawn afterwards.
/// Nothing happens if the view is gone by then. Hold or detach the returned task.
pub fn spawn<V, R>(
    cx: &mut Context<V>,
    work: impl FnOnce() -> anyhow::Result<R> + Send + 'static,
    done: impl FnOnce(&mut V, anyhow::Result<R>, &mut Context<V>) + 'static,
) -> Task<()>
where
    V: 'static,
    R: Send + 'static,
{
    cx.spawn(async move |this, cx| {
        let result = cx.background_spawn(async move { work() }).await;
        this.update(cx, |view, cx| {
            done(view, result, cx);
            cx.notify();
        })
        .ok();
    })
}

/// [`spawn`] for a `done` that needs the window, e.g. to set an input's text.
pub fn spawn_in<V, R>(
    window: &Window,
    cx: &mut Context<V>,
    work: impl FnOnce() -> anyhow::Result<R> + Send + 'static,
    done: impl FnOnce(&mut V, anyhow::Result<R>, &mut Window, &mut Context<V>) + 'static,
) -> Task<()>
where
    V: 'static,
    R: Send + 'static,
{
    cx.spawn_in(window, async move |this, cx| {
        let result = cx.background_spawn(async move { work() }).await;
        this.update_in(cx, |view, window, cx| {
            done(view, result, window, cx);
            cx.notify();
        })
        .ok();
    })
}
