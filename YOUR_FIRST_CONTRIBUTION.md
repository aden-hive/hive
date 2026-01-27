# Your First Contribution - Action Plan

## 🎯 Goal: Make a Real Contribution That Helps the Project Grow

---

## Step 1: Install Python (5 minutes)

1. **Download Python 3.11 or 3.12:**
   - Go to: https://www.python.org/downloads/
   - Download the latest 3.11 or 3.12 version
   - **CRITICAL:** During installation, check ✅ "Add Python to PATH"

2. **Verify Installation:**
   ```powershell
   python --version
   ```
   Should show: `Python 3.11.x` or `Python 3.12.x`

3. **If it doesn't work:**
   - Restart your terminal/PowerShell
   - Or manually add Python to PATH (Google: "add python to PATH windows")

---

## Step 2: Set Up the Project (10 minutes)

```powershell
# You're already in the hive directory, so:

# Install dependencies
./scripts/setup-python.sh

# If that doesn't work on Windows, try:
cd core
pip install -e .
cd ../tools
pip install -e .
cd ..
```

---

## Step 3: Find Real Issues to Work On

### Option A: Check GitHub Issues (BEST)
1. Go to: https://github.com/adenhq/hive/issues
2. Look for:
   - Issues labeled `good first issue` or `help wanted`
   - Bugs that affect users
   - Features from the roadmap

### Option B: Work on Roadmap Items

From `ROADMAP.md`, here are **real features** that need work:

#### 🟢 Good for Learning (Start Here):
1. **Sample Agents** (Lines 94-96)
   - Knowledge Agent
   - Blog Writer Agent  
   - SDR Agent
   - **Why:** You'll learn the framework by building with it
   - **Impact:** Shows users what's possible

2. **Debugging Mode** (Line 81)
   - **Why:** Helps developers build better agents
   - **Impact:** Improves developer experience

#### 🟡 Medium Difficulty:
3. **Audit Trail Tool** (Line 61)
   - Track agent decisions over time
   - **Why:** Needed for production use
   - **Impact:** Better observability

4. **Pydantic Validation** (Line 78)
   - Ensure LLM outputs match expected structure
   - **Why:** Makes agents more reliable
   - **Impact:** Fewer runtime errors

#### 🔴 Advanced (Later):
5. **Streaming Interface** (Line 51)
6. **JavaScript SDK** (Line 111)

---

## Step 4: Make Your First Contribution

### A. Pick an Issue
- Comment on GitHub: "I'd like to work on this!"
- Wait for assignment (usually within 24 hours)

### B. Create Your Branch
```powershell
git checkout -b feature/your-feature-name
# Example: git checkout -b feature/add-knowledge-agent
```

### C. Make Changes
- Write code
- Test it works
- Follow code style (see CONTRIBUTING.md)

### D. Test Your Changes
```powershell
# Test core framework
cd core
python -m pytest

# Test tools
cd ../tools
python -m pytest
```

### E. Submit Pull Request
```powershell
git add .
git commit -m "feat(component): add your feature"
git push origin feature/your-feature-name
```

Then create PR on GitHub.

---

## Recommended First Contribution: Build a Sample Agent

**Why this is perfect:**
- ✅ You learn the framework by using it
- ✅ Shows real value (demonstrates capabilities)
- ✅ Can start simple and improve
- ✅ No deep framework knowledge needed

**Pick one:**
1. **Knowledge Agent** - Answers questions from documents
2. **Blog Writer Agent** - Writes blog posts from topics
3. **SDR Agent** - Sales development rep that finds leads

**How to start:**
1. Look at existing agents in `exports/` (if any)
2. Use the `/building-agents` skill (if you have Claude Code)
3. Or manually create following the structure in `DEVELOPER.md`

---

## Need Help?

- **Discord:** https://discord.com/invite/MXE49hrKDk
- **GitHub Issues:** https://github.com/adenhq/hive/issues
- **Documentation:** See `DEVELOPER.md` and `docs/`

---

## Remember

- **Quality > Speed:** Better to submit one good PR than many rushed ones
- **Ask Questions:** The team wants you to succeed
- **Start Small:** You can always expand your contribution later
- **Learn as You Go:** This is how you'll grow your Python skills!

Good luck! 🚀
