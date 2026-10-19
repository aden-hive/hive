// Prompt catalog metadata (categories / queen routing). The prompt list
// itself now lives in the cloud catalog (GET /v1/community-prompts).

export interface Prompt {
  id: number;
  title: string;
  category: string;
  content: string;
}


export const promptCategories = [
  { id: "marketing", name: "Marketing & Growth", count: 66, color: "bg-slate-500/10 text-slate-600" },
  { id: "sales", name: "Sales & Business Development", count: 60, color: "bg-slate-500/10 text-slate-600" },
  { id: "support", name: "Customer Success & Support", count: 50, color: "bg-slate-500/10 text-slate-600" },
  { id: "product", name: "Product & Engineering", count: 50, color: "bg-slate-500/10 text-slate-600" },
  { id: "finance", name: "Finance & Accounting", count: 40, color: "bg-slate-500/10 text-slate-600" },
  { id: "hr", name: "HR & People Operations", count: 50, color: "bg-slate-500/10 text-slate-600" },
  { id: "legal", name: "Legal & Compliance", count: 40, color: "bg-slate-500/10 text-slate-600" },
  { id: "operations", name: "Operations & Supply Chain", count: 40, color: "bg-slate-500/10 text-slate-600" },
  { id: "data", name: "Data & Analytics", count: 40, color: "bg-slate-500/10 text-slate-600" },
  { id: "executive", name: "Executive & Administrative", count: 40, color: "bg-slate-500/10 text-slate-600" },
  { id: "security", name: "IT & Security", count: 30, color: "bg-slate-500/10 text-slate-600" },
];
// Auto-generated category to queen mapping
// Maps prompt categories to the appropriate queen for routing

export const categoryToQueen: Record<string, string> = {
  // Brand & Marketing (60 prompts)
  "marketing": "queen_growth",           // Marketing & Growth → Head of Growth, a default GTM queen

  // Growth & Revenue (60 prompts)
  "sales": "queen_outbound",             // Sales & Business Development → Head of Outbound, a default GTM queen
  
  // Product (50 prompts)
  "product": "queen_product_strategy",   // Product & Engineering → Head of Product
  
  // Technology & Engineering (80 prompts total)
  "data": "queen_technology",            // Data & Analytics → Head of Technology
  "security": "queen_technology",        // IT & Security → Head of Technology
  
  // Finance (40 prompts)
  "finance": "queen_finance_fundraising", // Finance & Accounting → Head of Finance
  
  // People (50 prompts)
  "hr": "queen_talent",                  // HR & People Operations → Head of Talent
  
  // Legal (40 prompts)
  "legal": "queen_legal",                // Legal & Compliance → Head of Legal
  
  // Operations (130 prompts total)
  "operations": "queen_operations",      // Operations & Supply Chain → Head of Operations
  "support": "queen_operations",         // Customer Success & Support → Head of Operations
  "executive": "queen_operations",       // Executive & Administrative → Head of Operations
};
export const queenNames: Record<string, string> = {
  "queen_market_research": "Head of Market Research",
  "queen_content_creation": "Head of Content",
  "queen_lead_gen": "Head of Lead Generation",
  "queen_outbound": "Head of Outbound",
  "queen_growth": "Head of Growth",
  "queen_technology": "Head of Technology",
  "queen_product_strategy": "Head of Product",
  "queen_finance_fundraising": "Head of Finance",
  "queen_legal": "Head of Legal",
  "queen_brand_design": "Head of Brand",
  "queen_talent": "Head of Talent",
  "queen_operations": "Head of Operations",
};
