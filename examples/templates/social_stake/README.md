# SocialStake Agent

AI-governed financial accountability protocol that helps users improve social skills by staking USDC.

## Overview

SocialStake is an AI-powered accountability system where users:
1. Set a social improvement goal (e.g., networking, public speaking)
2. Stake USDC as a commitment
3. Receive daily check-ins and motivation
4. Submit proof of social interactions (photos, reports, calendar events, videos)
5. Get verified by the AI Arbiter
6. Receive funds back based on verified progress

## Features

- **Timer-triggered daily check-ins**: Automated reminders using `trigger_type="timer"`
- **Multi-modal proof verification**: Supports photos, meeting reports, calendar events, and videos
- **Progressive stake release**: Funds released proportionally to verified progress
- **Continuous engagement**: Forever-alive agent with continuous conversation mode

## Workflow

```
intake -> stake-setup -> notify -> daily-checkin (loop) -> verify-proof ->
update-progress -> notify -> (daily-checkin or settle-stake) -> notify -> intake
```

## Usage

### CLI Commands

```bash
# Show agent info
uv run python -m social_stake info

# Validate agent structure
uv run python -m social_stake validate

# Run interactive session
uv run python -m social_stake shell

# Execute workflow
uv run python -m social_stake run
```

### As a Module

```python
from social_stake import SocialStakeAgent, default_agent

# Get agent info
info = default_agent.info()

# Validate structure
validation = default_agent.validate()

# Run the agent
import asyncio
result = asyncio.run(default_agent.run({"goal": "networking"}))
```

## Node Reference

| Node | Type | Description |
|------|------|-------------|
| `intake` | Client-facing | Collect user's goal, stake amount, and commitment |
| `stake-setup` | Internal | Initialize on-chain stake |
| `daily-checkin` | Client-facing | Daily reminder and progress collection |
| `verify-proof` | Internal | AI verification of submitted proofs |
| `update-progress` | Internal | Update progress tracker |
| `settle-stake` | Client-facing | Release or forfeit stake at deadline |
| `notify` | Client-facing | Send notifications to user |

## Entry Points

- **Default** (`manual`): User-initiated stake creation
- **Daily Timer** (`timer`): Automated daily check-ins (every 1440 minutes)

## Settlement Rules

| Progress | Stake Released |
|----------|---------------|
| 100% | 100% |
| 75-99% | 75% |
| 50-74% | 50% |
| 25-49% | 25% |
| <25% | 0% (forfeit) |

## Constraints

- **Fund Safety**: Stake only released based on verified progress
- **Verification Integrity**: Objective, unbiased proof verification
- **User Privacy**: Personal data handled with care
- **Minimum Stake**: 10 USDC minimum
- **Supportive Tone**: Encouraging, non-judgmental interactions

## Testing

```bash
cd core
uv run pytest ../examples/templates/social_stake/tests/ -v
```
