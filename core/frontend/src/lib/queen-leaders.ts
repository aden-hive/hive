import { queenRoleLabel } from "@/components/QueenSelect";
import type { PortraitDescriptor } from "@/api/queens";

/**
 * Leader-persona catalog ported from the signup site
 * (open-hive-site/components/Onboarding/queen-leaders.ts). Each queen function
 * has a set of famous-person personas the queen can be modeled after. The
 * desktop renders these in the org chart's decommissioned panel as a hireable
 * gallery. Keep in sync with the signup site if its roster changes.
 */
export interface QueenLeader {
  /** Internal id of the lead template (e.g. "wintour"). */
  id: string;
  /** Display name of the public figure (e.g. "Anna Wintour"). */
  n: string;
  /** Org affiliation tag (e.g. "Vogue"). */
  t: string;
  /** Persona description. */
  bio: string;
  /** Portrait parameters consumed by QueenPortraitGlyph. */
  p: PortraitDescriptor;
}

/**
 * Last-resort label for a queen function, derived from its id.
 *
 * There is exactly ONE definition of a queen's display name: the `title` on her
 * profile, which the runtime serves for every catalog queen (materialized or
 * not — see `list_queens`) and which the user can edit in the profile panel.
 * `queenFunctionLabel` reads that; this is only what it falls back to in the
 * moment before profiles have loaded.
 *
 * Deliberately a DERIVATION, not a table. A hardcoded id → label map is a second
 * definition, and a second definition is a second thing to forget: renaming a
 * queen used to mean editing her profile yaml AND this map, so the org chart
 * kept showing the old name long after everywhere else had moved on.
 */
export function queenLabelFromId(functionId: string): string {
  return functionId
    .replace(/^queen_/, "")
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/**
 * The display label for a queen function — "RevOps", "Lead Gen", … — resolved
 * from her profile title ("Head of RevOps" → "RevOps"), which is the single
 * source of truth for what she is called.
 */
export function queenFunctionLabel(
  profiles: { id: string; title?: string | null }[],
  functionId: string,
): string {
  const title = profiles.find((p) => p.id === functionId)?.title;
  return queenRoleLabel(title ?? undefined) ?? queenLabelFromId(functionId);
}

export const QUEEN_LEADERS: Record<string, QueenLeader[]> = {
  queen_market_research: [
    { id: "meeker", n: "Mary Meeker", t: "Bond · KPCB", bio: "Queen of the Internet. Her annual trends report set the agenda for a generation; reads markets through data the way others read headlines.",
      p: { skin: "#F0CFA8", hair: "#C8AE86", cut: "bob-long", face: "oval", mouth: "smile-soft", glasses: "rect", shirt: "shirt-blue" } },
    { id: "kotler", n: "Philip Kotler", t: "Kellogg", bio: "The father of modern marketing. Turned market research into a discipline; if it can be segmented, targeted, and positioned, he wrote the framework.",
      p: { skin: "#F0CFA8", hair: "#E5DECF", cut: "side-back-grey", face: "oval", glasses: "rect", mouth: "smile-soft", shirt: "shirt-tie" } },
    { id: "christensen", n: "Clayton Christensen", t: "Harvard", bio: "Disruption theorist. Asks what job customers hire a product to do; finds the markets incumbents literally cannot see.",
      p: { skin: "#F2D5B0", hair: "#E0D8C8", cut: "side-short-grey", face: "rect", glasses: "rect", mouth: "smile-soft", shirt: "shirt-tie" } },
    { id: "sharp", n: "Byron Sharp", t: "Ehrenberg-Bass", bio: "Marketing scientist. Burns down comfortable myths with data; explains how brands actually grow, not how we wish they did.",
      p: { skin: "#EFD0A8", hair: "#6B5A4A", cut: "short-back", face: "oval", beard: "stubble", glasses: "rect", mouth: "flat" } },
    { id: "ariely", n: "Dan Ariely", t: "Duke", bio: "Behavioral economist. Maps the predictable irrationality behind why people really buy — and why surveys lie.",
      p: { skin: "#E5C8A4", hair: "#2B2118", cut: "crop", face: "round", beard: "full", mouth: "smile-soft" } },
    { id: "sutherland", n: "Rory Sutherland", t: "Ogilvy", bio: "Ad-man philosopher. Finds the psychological value others miss; reframes the problem until the cheap answer appears.",
      p: { skin: "#EFCDA6", hair: "#9B8A76", cut: "bald-shine", face: "round", glasses: "round", mouth: "smile-broad", shirt: "shirt-tie" } },
    { id: "silver", n: "Nate Silver", t: "FiveThirtyEight", bio: "Forecaster. Separates signal from noise; hands you probabilities and confidence intervals instead of pundit certainty.",
      p: { skin: "#EFCDA6", hair: "#3D332B", cut: "short", face: "oval", beard: "stubble", glasses: "rect", mouth: "flat" } },
    { id: "fleming", n: "Colin Fleming", t: "Market Insight", bio: "Reads the market like a brand strategist — pairs hard category data with the cultural signal behind it, and finds the story the numbers are trying to tell.",
      p: { skin: "#E8C49E", hair: "#3D332B", cut: "short", face: "oval", beard: "stubble", mouth: "smile-soft", shirt: "shirt-blue" } },
  ],
  queen_content_creation: [
    { id: "garyvee", n: "Gary Vaynerchuk", t: "VaynerMedia", bio: "Attention is the asset. Document, don't create; make fifty pieces, learn from three. Patient brand builder hiding behind the energy.",
      p: { skin: "#E5BD90", hair: "#1A1410", cut: "short-back", face: "round", beard: "stubble", mouth: "smile-broad", eyes: "sharp", shirt: "tee-grey" } },
    { id: "mrbeast", n: "Jimmy Donaldson", t: "MrBeast", bio: "The most-watched creator on Earth. Engineers attention at industrial scale; obsesses over the first three seconds of everything.",
      p: { skin: "#F2D6B8", hair: "#5C4131", cut: "short", face: "round", beard: "stubble", mouth: "smile-broad", eyes: "wide", shirt: "tee-black" } },
    { id: "ogilvy", n: "David Ogilvy", t: "Ogilvy & Mather", bio: "The father of advertising. The consumer is not a moron; long copy that sells and headlines that earn the read.",
      p: { skin: "#F0CFA8", hair: "#D2CCC0", cut: "side-back-grey", face: "oval", moustache: true, mouth: "smile-soft", shirt: "shirt-tie" } },
    { id: "neistat", n: "Casey Neistat", t: "Filmmaker", bio: "Vlog auteur. Story first, gear second; built an audience on craft and the discipline of shipping every single day.",
      p: { skin: "#EAC2A0", hair: "#3A2E26", cut: "crop", face: "oval", beard: "stubble", mouth: "smile", eyes: "sharp", shirt: "tee-black" } },
    { id: "gerhardt", n: "Dave Gerhardt", t: "Exit Five", bio: "B2B marketing's loudest advocate. Built brand and demand at Drift and Privy, now runs Exit Five — living proof that B2B content doesn't have to be boring.",
      p: { skin: "#EAC4A0", hair: "#3D332B", cut: "short", face: "oval", beard: "stubble", mouth: "smile-broad", shirt: "tee-grey" } },
    { id: "forleo", n: "Marie Forleo", t: "MarieTV", bio: "Built a media empire on warmth and consistency. Everything is figureoutable; show up, serve, repeat until it compounds.",
      p: { skin: "#EFCDA6", hair: "#4A3A2E", cut: "long-straight", face: "oval", mouth: "smile-broad" } },
    { id: "handley", n: "Ann Handley", t: "MarketingProfs", bio: "Made B2B content human. Everybody writes; few write well — she teaches the difference, one ruthless edit at a time.",
      p: { skin: "#F0CEA6", hair: "#9C7A56", cut: "long-wavy", face: "oval", glasses: "rect", mouth: "smile-broad" } },
    { id: "verna", n: "Elena Verna", t: "Growth Advisor", bio: "Growth leader turned prolific creator. Ran growth at Miro and SurveyMonkey; now teaches a generation of operators through a newsletter and posts the whole industry reads.",
      p: { skin: "#F0CFA8", hair: "#3A2E26", cut: "long-wavy", face: "oval", mouth: "smile", eyes: "sharp" } },
  ],
  queen_lead_gen: [
    { id: "hormozi", n: "Alex Hormozi", t: "Acquisition.com", bio: "Wrote $100M Leads. Treats lead generation as a math problem — a great offer in front of enough of the right people, enough times. Volume times value.",
      p: { skin: "#E5BD90", hair: "#1A1410", cut: "bald-shine", face: "square", beard: "full", mouth: "flat", eyes: "sharp", shirt: "tee-black" } },
    { id: "aross", n: "Aaron Ross", t: "Predictable Revenue", bio: "Wrote Predictable Revenue — turned lead generation into a repeatable system of specialized roles and clean lists. Calm, methodical, deeply pro-rep.",
      p: { skin: "#EAC4A0", hair: "#5C4131", cut: "short", face: "oval", beard: "stubble", mouth: "smile-soft" } },
    { id: "halligan", n: "Brian Halligan", t: "HubSpot", bio: "Co-founded HubSpot and coined \"inbound\" — earn attention with content so good that qualified leads come to you, then capture and nurture them at scale.",
      p: { skin: "#EFCDA6", hair: "#C9C2B8", cut: "side-back-grey", face: "oval", mouth: "smile-soft", shirt: "shirt-blue" } },
    { id: "dshah", n: "Dharmesh Shah", t: "HubSpot", bio: "HubSpot co-founder and CTO. Built the inbound lead engine the industry copied; obsesses over the funnel from anonymous visitor to qualified lead.",
      p: { skin: "#D9B595", hair: "#1A1410", cut: "bald-shine", face: "oval", glasses: "rect", beard: "stubble", mouth: "smile-soft" } },
    { id: "fishkin", n: "Rand Fishkin", t: "SparkToro", bio: "Founded Moz, then SparkToro. Maps exactly where your audience pays attention so lead gen targets the right people in the right places.",
      p: { skin: "#EFD0A8", hair: "#3A2E26", cut: "crop", face: "round", beard: "full", glasses: "rect", mouth: "smile" } },
    { id: "ingram", n: "Morgan Ingram", t: "Creator", bio: "Prospecting creator who turned cold outreach into a teachable system — multi-channel sequences that actually book meetings.",
      p: { skin: "#8B5E3C", hair: "#1A1410", cut: "short", face: "oval", beard: "stubble", mouth: "smile-broad", eyes: "kind" } },
  ],
  queen_outbound: [
    { id: "voss", n: "Chris Voss", t: "Black Swan Group", bio: "The FBI's lead international kidnapping negotiator turned author of Never Split the Difference. Tactical empathy, calibrated questions, and the late-night FM-DJ voice — gets to yes without ever pushing.",
      p: { skin: "#EFCDA6", hair: "#C9C2B8", cut: "bald-shine", face: "oval", glasses: "rect", mouth: "smile-soft", shirt: "shirt-blue" } },
    { id: "welsh", n: "Justin Welsh", t: "The Saturday Solopreneur", bio: "Built an eight-figure solo business on LinkedIn and Twitter. Systematizes personal brand and outbound into a repeatable daily engine.",
      p: { skin: "#EFCDA6", hair: "#3D332B", cut: "short", face: "oval", beard: "stubble", mouth: "smile-soft", shirt: "tee-grey" } },
    { id: "bloom", n: "Sahil Bloom", t: "Writer · Investor", bio: "Turned a Twitter thread habit into reach and deal flow. Master of the hook and the curiosity gap that earns the click.",
      p: { skin: "#E2BF96", hair: "#2B2118", cut: "short", face: "oval", beard: "stubble", mouth: "smile-soft" } },
    { id: "roberge", n: "Mark Roberge", t: "HubSpot", bio: "Engineered HubSpot's sales machine like a software product — measure, iterate, scale. The science behind the modern SaaS quota.",
      p: { skin: "#E5C8A4", hair: "#3D332B", cut: "short", face: "oval", mouth: "smile-soft", shirt: "shirt-blue" } },
    { id: "robbins", n: "Tony Robbins", t: "Robbins Research", bio: "Turned selling into a science of state, rapport, and certainty. Coached millions on influence and leverage; moves a hesitant \"no\" toward \"yes\" by changing how the room feels.",
      p: { skin: "#D9A878", hair: "#1A1410", cut: "short-back", face: "square", mouth: "smile-broad", eyes: "sharp", shirt: "tee-black" } },
    { id: "konrath", n: "Jill Konrath", t: "Author", bio: "Selling to busy buyers. Crisp, relevant, and respectful of the prospect's time — the exact opposite of spray-and-pray.",
      p: { skin: "#F0CFA8", hair: "#C8AE86", cut: "bob-long", face: "oval", glasses: "rect", mouth: "smile-soft" } },
    { id: "braun", n: "Josh Braun", t: "Sales DNA", bio: "Anti-pushy outbound. Lowers the resistance instead of raising the pressure; sells the way people actually want to be sold to.",
      p: { skin: "#EFCDA6", hair: "#9B8A76", cut: "bald-shine", face: "oval", glasses: "rect", beard: "stubble", mouth: "smile-soft" } },
    { id: "disney", n: "Daniel Disney", t: "The Daily Sales", bio: "The king of LinkedIn selling. Social selling that books meetings without the cringe; relevance over volume, every time.",
      p: { skin: "#EFCDA6", hair: "#3D332B", cut: "short-back", face: "rect", beard: "full", mouth: "smile", shirt: "shirt-blue" } },
  ],
  queen_technology: [
    { id: "musk", n: "Elon Musk", t: "Tesla · SpaceX", bio: "First-principles, high-velocity, fond of moonshots and tight deadlines. Plans bold; ships fast; expects everyone to keep up.",
      p: { skin: "#F0D2B0", hair: "#8B6E55", cut: "swept-front", face: "long", brow: "arched", mouth: "flat", eyes: "sharp", shirt: "tee-black" } },
    { id: "gates", n: "Bill Gates", t: "Microsoft", bio: "Strategic, voraciously curious, books-and-spreadsheets brain. Plays long games; will redirect resources fast when the data shifts.",
      p: { skin: "#EFD6BC", hair: "#A88E6F", cut: "parted", glasses: "square", face: "round", mouth: "smile-soft", shirt: "sweater-vee" } },
    { id: "huang", n: "Jensen Huang", t: "NVIDIA", bio: "Bets a decade ahead and works backwards. Wants the platform fight, not the feature fight. Direct, technical, allergic to slow.",
      p: { skin: "#E2BF96", hair: "#E5DBC8", cut: "short-back", face: "rect", mouth: "smile", leather: true, eyes: "kind", glasses: "rect-thick" } },
    { id: "amodei", n: "Dario Amodei", t: "Anthropic", bio: "Princeton physicist who left OpenAI to build Anthropic. Believes in shaping powerful AI with constitutional rails; quiet, principled, ships at the frontier.",
      p: { skin: "#EFD2A8", hair: "#2B2118", cut: "wild-curly", face: "oval", glasses: "rect-blue", mouth: "smile-soft", eyes: "kind", shirt: "tee-grey" } },
    { id: "nadella", n: "Satya Nadella", t: "Microsoft", bio: "Empathy as strategy. Repositioned a giant around cloud and AI; quiet, relentless, and deeply engineering-literate.",
      p: { skin: "#D9B595", hair: "#1A1410", cut: "bald-shine", face: "oval", glasses: "rect", mouth: "smile-soft" } },
    { id: "pichai", n: "Sundar Pichai", t: "Google", bio: "Calm operator of a planetary-scale platform. Builds consensus, ships at scale, bets multi-year on shifts before they're obvious.",
      p: { skin: "#C99270", hair: "#1F1A16", cut: "side-back", face: "oval", beard: "stubble", mouth: "smile-soft", glasses: "rect" } },
    { id: "hassabis", n: "Demis Hassabis", t: "DeepMind", bio: "Chess prodigy turned protein folder. Treats AGI as a science problem; rigorous, curious, eyes on the long arc of intelligence.",
      p: { skin: "#EAC4A0", hair: "#1F1A16", cut: "bald-shine", face: "round", mouth: "smile-soft", glasses: "rect-blue" } },
  ],
  queen_operations: [
    { id: "cook", n: "Tim Cook", t: "Apple", bio: "Quiet operator. Believes systems beat heroics; every detail audited, every supplier known by name.",
      p: { skin: "#E6C5A4", hair: "#C9C2B8", cut: "side-short-grey", face: "oval", mouth: "flat", eyes: "kind", shirt: "tee-black" } },
    { id: "bezos", n: "Jeff Bezos", t: "Amazon", bio: "Customer-obsessed, two-pizza teams, written six-pagers. Builds flywheels and waits patiently for the spin.",
      p: { skin: "#E8C49E", hair: "#1F1F1F", cut: "bald-shine", face: "round", mouth: "smile-broad", eyes: "sharp", shirt: "shirt-blue" } },
    { id: "mary", n: "Mary Barra", t: "GM", bio: "Engineer-turned-CEO who runs operations like a precision machine. Calm, decisive, speaks from the factory floor.",
      p: { skin: "#F0CFA8", hair: "#A4845E", cut: "bob-long", face: "oval", mouth: "smile-soft" } },
    { id: "fadell", n: "Tony Fadell", t: "iPod · Nest", bio: "Hardware-software systems thinker. Sweats every screw, every word in the box. Direct critic, rigorous mentor.",
      p: { skin: "#E5BD90", hair: "#1F1A16", cut: "crop", glasses: "rect-thick", face: "rect", beard: "stubble" } },
    { id: "dimon", n: "Jamie Dimon", t: "JPMorgan", bio: "Fortress balance sheet, plain talk, war-room operations. Plans for storms; runs the bank like it's 1907.",
      p: { skin: "#EFC9A0", hair: "#B5B0A6", cut: "side-short-grey", face: "rect", mouth: "flat", shirt: "shirt-tie" } },
    { id: "nooyi", n: "Indra Nooyi", t: "PepsiCo", bio: "Strategic, data-rich, performance-with-purpose operator. Reshaped a giant portfolio toward better-for-you while never missing a number.",
      p: { skin: "#C99270", hair: "#1A1410", cut: "long-straight", face: "oval", mouth: "smile-soft" } },
    { id: "mcmillon", n: "Doug McMillon", t: "Walmart", bio: "Started in a Walmart distribution center, ended up running it. Deep respect for store associates, ruthless about supply-chain efficiency.",
      p: { skin: "#EFCDA6", hair: "#5C4A3A", cut: "side-short", face: "rect", mouth: "smile-soft", shirt: "shirt-tie" } },
  ],
  queen_product_strategy: [
    { id: "chesky", n: "Brian Chesky", t: "Airbnb", bio: "Lives inside the product. Sketches with designers, edits release notes, treats every pixel of the guest experience as personal.",
      p: { skin: "#EFCDA6", hair: "#1A1410", cut: "short", face: "oval", mouth: "smile-soft" } },
    { id: "collison", n: "Patrick Collison", t: "Stripe", bio: "Engineer-CEO who reads everything. Treats infrastructure as design; ships APIs like consumer apps. Stripe is what happens when product taste meets execution.",
      p: { skin: "#F2D8B8", hair: "#6B4A2E", cut: "short", face: "oval", mouth: "smile-soft" } },
    { id: "tlutke", n: "Tobi Lütke", t: "Shopify", bio: "Engineer-CEO who still ships code. Builds for merchants like himself; long memos, deep craft, treats Shopify as a hundred-year company.",
      p: { skin: "#EFCDA6", hair: "#7B5C42", cut: "crop", face: "oval", beard: "stubble", mouth: "smile-soft", glasses: "rect" } },
    { id: "ek", n: "Daniel Ek", t: "Spotify", bio: "Coded the first Spotify prototype to kill piracy. Wields data like a producer; sequenced the entire music industry from a Stockholm flat into a global rail.",
      p: { skin: "#EFD2A8", hair: "#2B2118", cut: "short", face: "oval", beard: "stubble", mouth: "smile-soft" } },
    { id: "dorsey", n: "Jack Dorsey", t: "Block", bio: "Two billion-dollar products from a notebook habit: 140 characters and tap-to-pay. Strips features until only the verb remains.",
      p: { skin: "#EAC2A0", hair: "#3A2E26", cut: "crop-thin", face: "oval", beard: "full", mouth: "flat" } },
    { id: "page", n: "Larry Page", t: "Google", bio: "Reorganized the world's information, then bet the company on the next ten years before anyone else saw it. Quiet, contrarian, allergic to incrementalism.",
      p: { skin: "#EFD0A8", hair: "#6B5A4A", cut: "side-short", face: "oval", mouth: "smile-soft" } },
    { id: "dyson", n: "James Dyson", t: "Dyson", bio: "Made 5,127 prototypes before the first cyclone sold. Believes great products start with frustration and end with engineering.",
      p: { skin: "#F2D5B0", hair: "#E5DECF", cut: "side-back-grey", face: "rect", mouth: "smile-soft", shirt: "shirt-blue" } },
  ],
  queen_sales: [
    { id: "ellison", n: "Larry Ellison", t: "Oracle", bio: "Combative, competitive, relentless on the close. Wins enterprise the old-fashioned way: out-sell, out-last.",
      p: { skin: "#E9C2A0", hair: "#7B6F62", cut: "side-back", face: "rect", beard: "stubble", mouth: "smirk" } },
    { id: "benioff", n: "Marc Benioff", t: "Salesforce", bio: "Big-tent evangelist. Treats sales as movement-building; reps are missionaries, customers are partners, every deal a story.",
      p: { skin: "#EAC0A0", hair: "#1A1614", cut: "long-wavy", face: "round", mouth: "smile-broad", beard: "stubble", shirt: "shirt-aloha" } },
    { id: "mcdermott", n: "Bill McDermott", t: "ServiceNow · SAP", bio: "Storyteller-CEO who took SAP from challenger to leader and now runs ServiceNow. Reads the room, leads with empathy, closes with conviction.",
      p: { skin: "#EFCDA6", hair: "#3D332B", cut: "side-back", face: "rect", mouth: "smile-broad", glasses: "sun", shirt: "shirt-tie" } },
    { id: "slootman", n: "Frank Slootman", t: "Snowflake · ServiceNow", bio: "Amp-it-up operator. Hates fluff, loves urgency. Picks great markets and demands every rep know the customer better than the customer does.",
      p: { skin: "#EFCAA0", hair: "#D2C9BA", cut: "short-back", face: "rect", mouth: "flat", brow: "arched", shirt: "shirt-tie" } },
    { id: "chambers", n: "John Chambers", t: "Cisco", bio: "Built the internet's plumbing one handshake at a time. Listens like an evangelist, sells like a hometown senator, calls the customer back personally.",
      p: { skin: "#F2D5B0", hair: "#D6CFC4", cut: "side-back-grey", face: "oval", mouth: "smile", shirt: "shirt-tie" } },
    { id: "aross", n: "Aaron Ross", t: "Predictable Revenue", bio: "Wrote the modern outbound playbook at Salesforce — specialized roles, cold email, repeatable pipeline. Calm, methodical, deeply pro-rep.",
      p: { skin: "#EAC4A0", hair: "#5C4131", cut: "short", face: "oval", beard: "stubble", mouth: "smile-soft" } },
    { id: "roberge", n: "Mark Roberge", t: "HubSpot", bio: "Engineered HubSpot's sales machine like a software product — measure, iterate, scale. The science behind the modern SaaS quota.",
      p: { skin: "#E5C8A4", hair: "#3D332B", cut: "short", face: "oval", mouth: "smile-soft", shirt: "shirt-blue" } },
  ],
  queen_growth: [
    { id: "jobs", n: "Steve Jobs", t: "Apple", bio: "Made marketing an art form. 'Think Different' wasn't a campaign — it was a worldview. Stage and stagecraft equal to the product itself.",
      p: { skin: "#E8D2B8", hair: "#2B2624", cut: "crop-thin", face: "oval", glasses: "round-rimless", beard: "stubble", mouth: "smile-soft", neck: "turtleneck" } },
    { id: "zuck", n: "Mark Zuckerberg", t: "Meta", bio: "Built the world's largest advertising machine on a feed nobody asked for. Bets on platform shifts ten years out; reorganizes to match.",
      p: { skin: "#F2D6B8", hair: "#7C5944", cut: "curls-fringe", face: "round", mouth: "flat", eyes: "wide" } },
    { id: "arnault", n: "Bernard Arnault", t: "LVMH", bio: "Heritage as moat. Stewards icons across LVMH with patience; protects desire by limiting access. Marketing as quiet authority.",
      p: { skin: "#EAC9A2", hair: "#C8C0B0", cut: "side-back-grey", face: "square", mouth: "flat", shirt: "shirt-tie" } },
    { id: "branson", n: "Richard Branson", t: "Virgin", bio: "The brand is the founder. Hot-air balloons, ribbon-cutting stunts, and a smile — extends a single name across 400 companies.",
      p: { skin: "#F2D8B6", hair: "#C7B098", cut: "wave-long", face: "oval", beard: "full", mouth: "smile-broad", eyes: "wide" } },
    { id: "knight", n: "Phil Knight", t: "Nike", bio: "Built Nike on stories before logos. Bet a generation on athletes-as-mythology; let the swoosh do the talking. Shoe Dog, page by page.",
      p: { skin: "#EFD2A8", hair: "#D2CCC0", cut: "side-back-grey", face: "oval", glasses: "round", mouth: "smile-soft" } },
    { id: "schultz", n: "Howard Schultz", t: "Starbucks", bio: "Sold the third place, not the coffee. Trained baristas like artists and made a green logo a daily ritual for millions.",
      p: { skin: "#EDC9A2", hair: "#4A4338", cut: "bald-shine", face: "oval", beard: "full-grey", mouth: "smile-soft", shirt: "shirt-tie" } },
    { id: "blakely", n: "Sara Blakely", t: "Spanx", bio: "Bootstrapped a billion-dollar brand on free PR and word-of-mouth. Sells confidence, not shapewear; her story is the campaign.",
      p: { skin: "#F4D9B8", hair: "#C49B6E", cut: "long-wavy", face: "oval", mouth: "smile-broad" } },
    { id: "poyar", n: "Kyle Poyar", t: "Growth Unhinged", bio: "Product-led growth's benchmark keeper. Turned OpenView's data into the PLG playbook; writes Growth Unhinged on pricing, packaging, and what actually moves the needle.",
      p: { skin: "#EFCDA6", hair: "#5C4131", cut: "short", face: "oval", beard: "stubble", mouth: "smile-soft", shirt: "shirt-blue" } },
  ],
  queen_finance_fundraising: [
    { id: "buffett", n: "Warren Buffett", t: "Berkshire Hathaway", bio: "Patience, moats, and circle of competence. Reads more than he talks; only swings at fat pitches.",
      p: { skin: "#F4DDB6", hair: "#E5DECF", cut: "side-bushy-grey", glasses: "square-thick", face: "round", mouth: "smile-soft", brow: "bushy" } },
    { id: "munger", n: "Charlie Munger", t: "Berkshire", bio: "Mental models, inversion, and a low tolerance for fools. Better to be roughly right than precisely wrong.",
      p: { skin: "#F4DDB6", hair: "#E5DECF", cut: "side-back-grey", glasses: "square-thick", face: "square", mouth: "flat", brow: "bushy" } },
    { id: "dalio", n: "Ray Dalio", t: "Bridgewater", bio: "Principles, radical transparency, debt cycles. Wants the truth no matter who delivers it.",
      p: { skin: "#EFD0A8", hair: "#D2CABB", cut: "short-grey", face: "oval", mouth: "flat" } },
    { id: "cathie", n: "Cathie Wood", t: "ARK Invest", bio: "Disruptive innovation, conviction trades, long-duration bets. Publishes the work, defends it on TV.",
      p: { skin: "#F0CFA8", hair: "#9B7E5C", cut: "long-straight", face: "oval", mouth: "smile-soft" } },
    { id: "powell", n: "Jerome Powell", t: "Federal Reserve", bio: "Steady-handed, data-dependent, calm under fire. Plays the long game with rates and language alike.",
      p: { skin: "#EDC9A2", hair: "#D2CCC0", cut: "side-back-grey", face: "oval", mouth: "flat", shirt: "shirt-tie" } },
    { id: "fink", n: "Larry Fink", t: "BlackRock", bio: "Stewards the world's biggest pool of capital with quiet authority. Reads macro like a long letter; cares about systems and stewardship.",
      p: { skin: "#F0CEA6", hair: "#D2CABB", cut: "side-back-grey", face: "oval", glasses: "rect", mouth: "flat", shirt: "shirt-tie" } },
    { id: "marks", n: "Howard Marks", t: "Oaktree", bio: "Memos that move markets. Cycles, second-level thinking, and the courage to be different — and right — at the same time.",
      p: { skin: "#EFCDA6", hair: "#E5DCCC", cut: "short-grey", face: "oval", glasses: "rect", mouth: "smile-soft" } },
  ],
  queen_talent: [
    { id: "altman", n: "Sam Altman", t: "OpenAI · YC", bio: "Built YC into the founder farm of a generation, then assembled the AI lab that defines the field. Concentrates the best people on the few bets that compound.",
      p: { skin: "#EFCEAA", hair: "#5C4131", cut: "side-short", face: "round", mouth: "smile-soft", eyes: "kind", shirt: "tee-grey" } },
    { id: "hastings", n: "Reed Hastings", t: "Netflix", bio: "Wrote the culture deck the rest of the industry copied. Hires adults, gives context, expects judgment. Allergic to process for its own sake.",
      p: { skin: "#EFCDA6", hair: "#3D332B", cut: "side-back", face: "oval", beard: "stubble", mouth: "smile-soft" } },
    { id: "reed", n: "Reid Hoffman", t: "LinkedIn", bio: "Network thinker, blitzscaling theorist. Hires for trajectory and bets on people early.",
      p: { skin: "#EFCDA6", hair: "#2A2520", cut: "short", face: "round", glasses: "rect", mouth: "smile-soft" } },
    { id: "patty", n: "Patty McCord", t: "Netflix culture", bio: "Hire adults, give them context, get out of the way. Burned the rulebook; wrote the deck.",
      p: { skin: "#F1D2AE", hair: "#A48564", cut: "long-wavy", face: "oval", mouth: "smile" } },
    { id: "hsieh", n: "Tony Hsieh", t: "Zappos", bio: "Happiness as a strategy. Believed culture eats strategy and proved it through customer service.",
      p: { skin: "#E5C8A4", hair: "#1A1410", cut: "crop", face: "round", mouth: "smile-broad" } },
    { id: "arianna", n: "Arianna Huffington", t: "Thrive", bio: "Founder of HuffPost and Thrive. Champions sleep, well-being, and the long career.",
      p: { skin: "#F0CEA6", hair: "#9C7A56", cut: "long-straight", face: "oval", mouth: "smile-broad" } },
    { id: "kscott", n: "Kim Scott", t: "Radical Candor", bio: "Care personally, challenge directly. Made hard feedback teachable; helps managers stop ruinous-empathy loops without becoming jerks.",
      p: { skin: "#F0CDA6", hair: "#5C4631", cut: "long-wavy", face: "oval", mouth: "smile-soft" } },
  ],
  queen_legal: [
    { id: "karp", n: "Alex Karp", t: "Palantir", bio: "Doctorate in jurisprudence; runs Palantir like a philosophy seminar with classified material. Argues from first principles, hates platitudes, and outlasts everyone in the room.",
      p: { skin: "#EAC7A2", hair: "#D8D2C5", cut: "wild-curly-grey", face: "oval", glasses: "round-rimless", beard: "stubble", mouth: "flat" } },
    { id: "thiel", n: "Peter Thiel", t: "Founders Fund", bio: "Stanford JD turned contrarian operator. Argues from monopoly first principles; bets on what others find unfashionable. Reads constitutions like balance sheets.",
      p: { skin: "#F2D8B8", hair: "#C4B5A2", cut: "side-short", face: "oval", mouth: "flat", shirt: "shirt-tie" } },
    { id: "tsai", n: "Joseph Tsai", t: "Alibaba", bio: "Yale Law to Alibaba co-founder. Negotiated the deals that built China's internet rail. Quiet leverage, decades-long relationships, plays every position on the board.",
      p: { skin: "#EFD2A8", hair: "#1A1410", cut: "side-back", face: "oval", glasses: "rect", mouth: "smile-soft", shirt: "shirt-tie" } },
    { id: "lefkofsky", n: "Eric Lefkofsky", t: "Tempus · Groupon", bio: "Michigan Law turned serial founder. Stacked four IPOs across InnerWorkings, Echo Global, Groupon, and Tempus — each built on a clean legal-corporate spine.",
      p: { skin: "#EFCDA6", hair: "#4A3A2E", cut: "crop-thin", face: "oval", glasses: "rect", mouth: "smile-soft" } },
    { id: "bonderman", n: "David Bonderman", t: "TPG", bio: "Harvard Law alum behind TPG. Specializes in distressed turnarounds and patient capital; reads contracts like other people read poetry.",
      p: { skin: "#F0CFA8", hair: "#E5DCCC", cut: "bald-shine", face: "oval", glasses: "rect", mouth: "flat", shirt: "shirt-tie" } },
    { id: "anschutz", n: "Phil Anschutz", t: "Anschutz Co.", bio: "Kansas Law grad who built an empire across energy, railroads, and entertainment. Quiet, religious, allergic to interviews — letters drive the company.",
      p: { skin: "#F0CFA8", hair: "#E0D8C8", cut: "side-back-grey", face: "oval", glasses: "rect", mouth: "flat", shirt: "shirt-tie" } },
    { id: "ross", n: "Stephen Ross", t: "Related Cos.", bio: "Wayne State JD and NYU tax LLM behind Related Companies. Hudson Yards, Equinox, the Miami Dolphins — every deal a real-estate stack with a legal floor plan.",
      p: { skin: "#F0CFA8", hair: "#E2DBCC", cut: "side-back-grey", face: "rect", mouth: "smile-soft", shirt: "shirt-tie" } },
  ],
  queen_brand_design: [
    { id: "ive", n: "Jony Ive", t: "Apple design", bio: "Soft-spoken obsessive. Believes design is what something does, not what it looks like.",
      p: { skin: "#EBC8A2", hair: "#7E6A56", cut: "crop-thin", face: "round", beard: "stubble", mouth: "smile-soft", shirt: "tee-grey" } },
    { id: "rams", n: "Dieter Rams", t: "Braun", bio: "Less, but better. Ten principles, every product a quiet argument for restraint.",
      p: { skin: "#F1D2AE", hair: "#E5DCCC", cut: "side-back-grey", glasses: "rect", face: "oval", mouth: "flat" } },
    { id: "ortega", n: "Amancio Ortega", t: "Inditex · Zara", bio: "Designed an empire on speed. Two weeks from sketch to shelf — Zara made the supply chain itself a design discipline. Famously private, lets the clothes do the talking.",
      p: { skin: "#EFD0A8", hair: "#D8D2C5", cut: "side-back-grey", face: "oval", mouth: "flat", shirt: "shirt-blue" } },
    { id: "wintour", n: "Anna Wintour", t: "Vogue", bio: "Famously decisive. The bob is the brand; the brand is taste, edited weekly without sentiment.",
      p: { skin: "#F2D5B0", hair: "#3F2E22", cut: "bob-sharp-bangs", glasses: "sun", face: "oval", mouth: "flat" } },
    { id: "ando", n: "Tadao Ando", t: "Architecture", bio: "Concrete, water, light. Self-taught, austere, makes spaces that feel like quiet arguments.",
      p: { skin: "#D8AC80", hair: "#1A1410", cut: "short-back", face: "rect", mouth: "flat", brow: "bushy" } },
    { id: "hara", n: "Kenya Hara", t: "Muji", bio: "Emptiness as design. Believes blankness is the highest form of communication when done with intent.",
      p: { skin: "#EBC59A", hair: "#1A1410", cut: "short", face: "oval", glasses: "round", mouth: "smile-soft" } },
    { id: "pscher", n: "Paula Scher", t: "Pentagram", bio: "Type as architecture. Citi, Public Theater, MoMA — built identities you can read from a city block, then defended every kerning fight.",
      p: { skin: "#F2D5B0", hair: "#E5DECF", cut: "long-wavy", face: "oval", mouth: "smile" } },
  ],
};

/** Flattened persona summary for rendering as a standalone card. */
export interface PersonaSummary {
  /** Stable composite id: `${functionId}__${leaderId}`. */
  id: string;
  functionId: string;
  leaderId: string;
  name: string;
  title: string;
  bio: string;
  portrait: PortraitDescriptor;
}

/** Look up a lead persona by its function id + leader id (e.g.
 *  `queen_growth`, `zuck`). Returns the full catalog entry — the source of
 *  truth for a lead's name/title/portrait — or undefined if unknown. */
export function leaderById(
  functionId: string,
  leaderId: string,
): QueenLeader | undefined {
  return QUEEN_LEADERS[functionId]?.find((l) => l.id === leaderId);
}

/** All personas as flat summaries, in the given function-id order. */
export function allPersonaSummaries(order: string[]): PersonaSummary[] {
  const functionIds = order.filter((id) => QUEEN_LEADERS[id]);
  // Append any catalog functions not present in the provided order.
  for (const id of Object.keys(QUEEN_LEADERS)) {
    if (!functionIds.includes(id)) functionIds.push(id);
  }
  return functionIds.flatMap((functionId) =>
    QUEEN_LEADERS[functionId].map((l) => ({
      id: `${functionId}__${l.id}`,
      functionId,
      leaderId: l.id,
      name: l.n,
      title: l.t,
      bio: l.bio,
      portrait: l.p,
    })),
  );
}
