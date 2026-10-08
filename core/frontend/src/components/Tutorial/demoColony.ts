/**
 * Shared identity for the tutorial's colony.
 *
 * Two distinct things live here, deliberately kept in one place so they read
 * as a pair:
 *
 *  - `DEMO_COLONY_TITLE` — the *scripted* colony shown during the tour. It's a
 *    controllable, hardcoded mock (see TutorialColonyDemo.tsx) and is what the
 *    sidebar renders as a fake "selected" row while the demo steps run.
 *
 *  - `STARTER_COLONY_*` — the *real* colony seeded on disk during first-run
 *    (see NewUserOnboarding.tsx → main/starter-colony.ts) so that once the tour
 *    ends the user has an actual, populated colony matching the theme they were
 *    just shown.
 */

/** Title of the scripted colony shown in the tutorial (fake, controllable). */
export const DEMO_COLONY_TITLE = "50 qualified leads for ICP outreach";

/** Colony id/slug for the real starter colony installed on first run. Displayed
 *  in the sidebar as "ICP Outreach" (see COLONY_DISPLAY_NAME_OVERRIDES — the
 *  slug title-cases to "Icp Outreach" otherwise). */
export const STARTER_COLONY_ID = "icp_outreach";

/** Queen that manages the real starter colony — matches the demo's "Head of
 *  Growth". */
export const STARTER_COLONY_QUEEN_ID = "queen_growth";
