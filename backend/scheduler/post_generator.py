"""Post generator — template-based LinkedIn post creation.

Contains 25 post templates (5 topics × 5 format types) pre-authored for
Taha's persona (Agentic AI & Senior Backend Engineer).

Format types: tip, insight, question, story, announcement
Topics: ai_automation, backend_development, hackathon_journey, cloud_devops, career_tips
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_CHARACTERS = 1300
INSTAGRAM_CHAR_LIMIT = 2_200
TWITTER_CHAR_LIMIT = 280

# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class PostTemplate:
    """A reusable post pattern for a specific topic and format type."""

    template_id: str
    topic_key: str
    format_type: str        # tip | insight | question | story | announcement
    body: str               # Final post text (no placeholders — Taha-specific)
    hashtags: list[str] = field(default_factory=list)


@dataclass
class PostContext:
    """Optional context from vault documents to enrich posts."""

    business_goals: str | None = None
    company_handbook: str | None = None


@dataclass
class GeneratedPost:
    """A generated social media post ready for saving."""

    body: str               # Full post text including hashtags
    hashtags: list[str]
    template_id: str
    character_count: int
    topic_key: str
    platform: str = "linkedin"  # linkedin | facebook | instagram


@dataclass
class ValidationResult:
    """Result of validating a generated post."""

    valid: bool
    character_count: int
    hashtag_count: int
    has_question: bool
    errors: list[str] = field(default_factory=list)


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES: dict[str, list[PostTemplate]] = {
    "ai_automation": [
        PostTemplate(
            template_id="ai_auto_tip_01",
            topic_key="ai_automation",
            format_type="tip",
            body=(
                "Building AI agents? Here's the most important lesson I've learned: 🤖\n\n"
                "Start with the simplest possible action loop before adding intelligence.\n\n"
                "My AI Employee project follows: Perception → Reasoning → Action.\n"
                "Each layer is independent, testable, and replaceable.\n\n"
                "When I separated email monitoring from decision-making from sending,\n"
                "debugging went from hours to minutes.\n\n"
                "What's your biggest challenge when structuring AI agent pipelines?\n\n"
                "#AIAgents #Automation #Python #SoftwareEngineering #BackendDev"
            ),
            hashtags=["#AIAgents", "#Automation", "#Python", "#SoftwareEngineering", "#BackendDev"],
        ),
        PostTemplate(
            template_id="ai_auto_insight_01",
            topic_key="ai_automation",
            format_type="insight",
            body=(
                "Unpopular opinion: most AI automation projects fail because of trust, not technology. 🎯\n\n"
                "Every AI action in my system requires human approval before execution.\n"
                "Emails go through HITL. LinkedIn posts go through HITL. Everything sensitive.\n\n"
                "Yes, it's slower. But it's also:\n"
                "✅ Auditable\n"
                "✅ Recoverable\n"
                "✅ Trustworthy\n\n"
                "The goal isn't full autonomy on day one — it's building trust incrementally.\n\n"
                "How much autonomy do you give your AI systems? I'd love to hear your approach.\n\n"
                "#AIAgents #HITL #Automation #AIEngineer #TrustInAI"
            ),
            hashtags=["#AIAgents", "#HITL", "#Automation", "#AIEngineer", "#TrustInAI"],
        ),
        PostTemplate(
            template_id="ai_auto_question_01",
            topic_key="ai_automation",
            format_type="question",
            body=(
                "Quick question for the AI builders in my network: 🧠\n\n"
                "When your AI agent makes a mistake, what's your recovery strategy?\n\n"
                "In my Personal AI Employee project, every action is:\n"
                "📝 Logged with correlation IDs\n"
                "🔄 Reversible where possible\n"
                "🚨 Alerted on failure\n\n"
                "But I'm curious — do you prefer:\n"
                "A) Fail fast and alert immediately\n"
                "B) Retry with exponential backoff\n"
                "C) Fallback to a safe default\n"
                "D) Something else entirely\n\n"
                "#AIAgents #Automation #ErrorHandling #AgenticAI #Engineering"
            ),
            hashtags=["#AIAgents", "#Automation", "#ErrorHandling", "#AgenticAI", "#Engineering"],
        ),
        PostTemplate(
            template_id="ai_auto_story_01",
            topic_key="ai_automation",
            format_type="story",
            body=(
                "The moment I realised AI automation changes everything: 💡\n\n"
                "Last week my AI Employee automatically:\n"
                "→ Detected an urgent email at 2 AM\n"
                "→ Drafted a professional reply\n"
                "→ Waited in my approval queue\n\n"
                "I approved it with one click at 8 AM. Client got a timely response.\n"
                "I got 6 hours of uninterrupted sleep.\n\n"
                "That's the real promise of agentic AI — not replacing humans,\n"
                "but extending what a single person can handle.\n\n"
                "What would you automate first if you had a personal AI employee?\n\n"
                "#AIAgents #Automation #PersonalAI #AgenticAI #FutureOfWork"
            ),
            hashtags=["#AIAgents", "#Automation", "#PersonalAI", "#AgenticAI", "#FutureOfWork"],
        ),
        PostTemplate(
            template_id="ai_auto_announce_01",
            topic_key="ai_automation",
            format_type="announcement",
            body=(
                "Excited to share a milestone on my Personal AI Employee project! 🚀\n\n"
                "Just implemented the full content scheduling loop:\n"
                "📋 Define topics once in a markdown file\n"
                "🤖 AI auto-generates LinkedIn drafts daily\n"
                "✅ Human reviews and approves in Obsidian\n"
                "📤 Auto-posts to LinkedIn after approval\n\n"
                "All template-based. No LLM API calls. Fast, deterministic, free.\n\n"
                "The architecture: template engine → vault file → HITL approval → action executor.\n\n"
                "Curious about the implementation details? Drop a comment below! 👇\n\n"
                "#AIAgents #Automation #OpenSource #Python #HackathonProject"
            ),
            hashtags=["#AIAgents", "#Automation", "#OpenSource", "#Python", "#HackathonProject"],
        ),
        PostTemplate(
            template_id="twitter_ai_01",
            topic_key="ai_automation",
            format_type="twitter_short",
            body=(
                "Building AI agents? Start simple.\n\n"
                "Perception → Reasoning → Action.\n\n"
                "My AI Employee monitors email/Twitter, drafts replies, waits for your OK. "
                "Agentic AI with human oversight 🤖\n\n"
                "#AIAgents #Python #Automation"
            ),
            hashtags=["#AIAgents", "#Python", "#Automation"],
        ),
    ],

    "backend_development": [
        PostTemplate(
            template_id="backend_tip_01",
            topic_key="backend_development",
            format_type="tip",
            body=(
                "Python async tip that saved my AI project hours of debugging: ⚡\n\n"
                "When mixing sync and async code, always use `asyncio.to_thread()`\n"
                "for blocking I/O — never `await` a sync function directly.\n\n"
                "Bad: `await sync_file_read()`  ← blocks the event loop\n"
                "Good: `await asyncio.to_thread(sync_file_read)`  ← non-blocking\n\n"
                "In my orchestrator, this kept watcher tasks responsive while\n"
                "the scheduler did file parsing in the background.\n\n"
                "What async patterns do you use to keep Python services snappy?\n\n"
                "#Python #AsyncPython #BackendDev #SoftwareEngineering #PythonTips"
            ),
            hashtags=["#Python", "#AsyncPython", "#BackendDev", "#SoftwareEngineering", "#PythonTips"],
        ),
        PostTemplate(
            template_id="backend_insight_01",
            topic_key="backend_development",
            format_type="insight",
            body=(
                "Hot take: the best system design decision I made this year was boring. 🏗️\n\n"
                "I chose flat JSON files over a database for my AI agent's state.\n\n"
                "Why? Because:\n"
                "→ Zero infrastructure to manage\n"
                "→ Human-readable in Obsidian\n"
                "→ Atomic writes prevent corruption\n"
                "→ Easy to debug with any text editor\n\n"
                "For single-user, local-first tools, a database is often over-engineering.\n\n"
                "The best architecture is the simplest one that meets your requirements.\n\n"
                "When do you reach for a database vs simpler persistence? Let me know.\n\n"
                "#SystemDesign #BackendDev #Python #SoftwareArchitecture #Engineering"
            ),
            hashtags=["#SystemDesign", "#BackendDev", "#Python", "#SoftwareArchitecture", "#Engineering"],
        ),
        PostTemplate(
            template_id="backend_question_01",
            topic_key="backend_development",
            format_type="question",
            body=(
                "Senior backend engineers: what's your go-to for service health monitoring? 🔍\n\n"
                "Building a watchdog for my AI agent system that auto-restarts\n"
                "crashed watchers (max 3 attempts, then alerts).\n\n"
                "Currently using a simple task loop with exponential backoff.\n"
                "Works great for a single-machine setup.\n\n"
                "But I'm curious about your production setups:\n"
                "→ supervisord?\n"
                "→ systemd service units?\n"
                "→ Kubernetes liveness probes?\n"
                "→ Something custom?\n\n"
                "#BackendDev #Python #DevOps #SRE #SoftwareEngineering"
            ),
            hashtags=["#BackendDev", "#Python", "#DevOps", "#SRE", "#SoftwareEngineering"],
        ),
        PostTemplate(
            template_id="backend_story_01",
            topic_key="backend_development",
            format_type="story",
            body=(
                "I spent 3 hours debugging a race condition that didn't exist. 😅\n\n"
                "The culprit? Forgetting that `Path.rename()` is atomic on NTFS\n"
                "but I was writing tests on a different filesystem.\n\n"
                "Lesson: always validate your \"simple\" assumptions in CI.\n\n"
                "Now I test atomic writes explicitly:\n"
                "1. Write to `.tmp` file\n"
                "2. Rename to final path\n"
                "3. Verify no `.tmp` files remain\n\n"
                "The boring infrastructure is always where the interesting bugs hide.\n\n"
                "What's your most surprising platform-specific bug story?\n\n"
                "#Python #BackendDev #Debugging #SoftwareEngineering #Testing"
            ),
            hashtags=["#Python", "#BackendDev", "#Debugging", "#SoftwareEngineering", "#Testing"],
        ),
        PostTemplate(
            template_id="backend_announce_01",
            topic_key="backend_development",
            format_type="announcement",
            body=(
                "Just implemented something I'm proud of in my AI project: 🛠️\n\n"
                "A complete MCP (Model Context Protocol) server for Gmail with:\n"
                "✅ OAuth 2.0 token management\n"
                "✅ Rate limiting (10 emails/hour)\n"
                "✅ Approval file verification before sending\n"
                "✅ Full audit logging with correlation IDs\n\n"
                "The coolest part? The AI can search/draft/reply emails,\n"
                "but can only SEND after a human approval file appears in the vault.\n\n"
                "Human-in-the-loop architecture FTW.\n\n"
                "Interested in the implementation? Happy to share more details!\n\n"
                "#Python #MCP #Gmail #BackendDev #AIAgents"
            ),
            hashtags=["#Python", "#MCP", "#Gmail", "#BackendDev", "#AIAgents"],
        ),
        PostTemplate(
            template_id="twitter_backend_01",
            topic_key="backend_development",
            format_type="twitter_short",
            body=(
                "Python async tip: use asyncio.to_thread() for blocking I/O.\n\n"
                "Never await a sync function directly — it blocks your event loop.\n\n"
                "What's your go-to async pattern? ⚡\n\n"
                "#Python #BackendDev #AsyncPython"
            ),
            hashtags=["#Python", "#BackendDev", "#AsyncPython"],
        ),
    ],

    "hackathon_journey": [
        PostTemplate(
            template_id="hackathon_tip_01",
            topic_key="hackathon_journey",
            format_type="tip",
            body=(
                "Hackathon tip from building a full AI employee system in 40+ hours: 🏆\n\n"
                "Spec before you code. Always.\n\n"
                "I spent the first 4 hours writing:\n"
                "→ User stories with acceptance scenarios\n"
                "→ Data model with entity schemas\n"
                "→ Interface contracts before any implementation\n\n"
                "Result: zero major architectural refactors mid-build.\n"
                "Every module fit together on the first try.\n\n"
                "The spec phase feels slow. The implementation phase proved it was fast.\n\n"
                "What's your pre-coding ritual before a hackathon?\n\n"
                "#Hackathon #SoftwareEngineering #SystemDesign #Python #AIAgents"
            ),
            hashtags=["#Hackathon", "#SoftwareEngineering", "#SystemDesign", "#Python", "#AIAgents"],
        ),
        PostTemplate(
            template_id="hackathon_insight_01",
            topic_key="hackathon_journey",
            format_type="insight",
            body=(
                "Building an AI Employee taught me something counterintuitive: 🧠\n\n"
                "The most valuable features aren't the AI parts.\n\n"
                "The HITL approval workflow, the audit logs, the DEV_MODE safety flag —\n"
                "these \"boring\" infrastructure pieces are what make the AI trustworthy.\n\n"
                "Anyone can call an LLM API. Shipping something you'd actually trust\n"
                "with your emails, posts, and finances? That's the hard part.\n\n"
                "My 40-hour hackathon project has more safety infrastructure\n"
                "than most production AI tools I've seen.\n\n"
                "What safety features do you consider non-negotiable in AI systems?\n\n"
                "#AIAgents #Hackathon #Safety #HITL #SoftwareEngineering"
            ),
            hashtags=["#AIAgents", "#Hackathon", "#Safety", "#HITL", "#SoftwareEngineering"],
        ),
        PostTemplate(
            template_id="hackathon_question_01",
            topic_key="hackathon_journey",
            format_type="question",
            body=(
                "Hackathon builders: what's your most impactful 'ship it' decision? 🚀\n\n"
                "Mine was choosing Obsidian vault files over a proper database.\n\n"
                "Instead of a UI, users manage the AI through markdown files.\n"
                "Approve an action? Move a file. Review a plan? Open a note.\n\n"
                "It's \"primitive\" but it meant I could ship a working system\n"
                "in 40 hours instead of 40 days.\n\n"
                "The best MVP is the one that ships.\n\n"
                "What constraint forced your most creative solution?\n\n"
                "#Hackathon #ProductThinking #AIAgents #MVP #SoftwareEngineering"
            ),
            hashtags=["#Hackathon", "#ProductThinking", "#AIAgents", "#MVP", "#SoftwareEngineering"],
        ),
        PostTemplate(
            template_id="hackathon_story_01",
            topic_key="hackathon_journey",
            format_type="story",
            body=(
                "Week 3 of the hackathon. Here's what I've shipped so far: 📊\n\n"
                "✅ Gmail watcher + email MCP server\n"
                "✅ Orchestrator with watchdog process management\n"
                "✅ LinkedIn poster with Playwright automation\n"
                "✅ Content scheduler (this very post was generated by it!)\n\n"
                "The architecture held up better than I expected.\n"
                "Perception → Reasoning → Action as separate layers\n"
                "made everything independently testable.\n\n"
                "Biggest surprise: writing specs first made coding 3x faster.\n\n"
                "What are you building this month?\n\n"
                "#Hackathon #AIAgents #Python #BuildInPublic #Progress"
            ),
            hashtags=["#Hackathon", "#AIAgents", "#Python", "#BuildInPublic", "#Progress"],
        ),
        PostTemplate(
            template_id="hackathon_announce_01",
            topic_key="hackathon_journey",
            format_type="announcement",
            body=(
                "Big milestone: my Personal AI Employee is now self-posting to LinkedIn! 🎉\n\n"
                "The full loop works:\n"
                "1️⃣ Scheduler generates draft from templates\n"
                "2️⃣ I review in Obsidian and move to Approved/\n"
                "3️⃣ Orchestrator detects approval\n"
                "4️⃣ LinkedIn poster publishes via Playwright\n"
                "5️⃣ Done/ folder records the history\n\n"
                "Yes — this post was drafted by my AI Employee and approved by me.\n"
                "Meta? Absolutely. 😄\n\n"
                "Want to follow the build? Comment below and I'll share updates!\n\n"
                "#Hackathon #AIAgents #BuildInPublic #LinkedIn #PersonalAI"
            ),
            hashtags=["#Hackathon", "#AIAgents", "#BuildInPublic", "#LinkedIn", "#PersonalAI"],
        ),
        PostTemplate(
            template_id="twitter_hackathon_01",
            topic_key="hackathon_journey",
            format_type="twitter_short",
            body=(
                "Hackathon update: shipped Twitter watcher + auto-poster for my Personal AI Employee 🚀\n\n"
                "Full HITL approval loop working. Spec → Tasks → Code → Tests.\n\n"
                "What are you building this month? #Hackathon #AIAgents #BuildInPublic"
            ),
            hashtags=["#Hackathon", "#AIAgents", "#BuildInPublic"],
        ),
    ],

    "cloud_devops": [
        PostTemplate(
            template_id="devops_tip_01",
            topic_key="cloud_devops",
            format_type="tip",
            body=(
                "Docker tip that every Python developer should know: 🐳\n\n"
                "Always use multi-stage builds for production Python images.\n\n"
                "Stage 1 (builder): Install all deps, compile extensions\n"
                "Stage 2 (runtime): Copy only what you need\n\n"
                "Result: My AI agent image went from 1.2GB to 180MB.\n"
                "Smaller images mean faster deploys and smaller attack surface.\n\n"
                "Bonus: combine with `uv` instead of pip for 10x faster dependency resolution.\n\n"
                "What Docker optimization has saved you the most time?\n\n"
                "#Docker #Python #DevOps #CloudNative #BackendDev"
            ),
            hashtags=["#Docker", "#Python", "#DevOps", "#CloudNative", "#BackendDev"],
        ),
        PostTemplate(
            template_id="devops_insight_01",
            topic_key="cloud_devops",
            format_type="insight",
            body=(
                "Kubernetes is often the wrong tool for the job. There, I said it. ☁️\n\n"
                "For my AI Employee project, I chose:\n"
                "→ Single Python process with asyncio tasks\n"
                "→ Windows Task Scheduler for cron-style startup\n"
                "→ Lock file for single-instance guarantee\n\n"
                "No Kubernetes. No Docker Compose. No orchestration platform.\n"
                "Just a well-structured Python program.\n\n"
                "For single-user, local-first tools, simplicity always wins.\n\n"
                "When do you reach for Kubernetes vs a simpler solution?\n\n"
                "#Kubernetes #DevOps #SystemDesign #CloudNative #Engineering"
            ),
            hashtags=["#Kubernetes", "#DevOps", "#SystemDesign", "#CloudNative", "#Engineering"],
        ),
        PostTemplate(
            template_id="devops_question_01",
            topic_key="cloud_devops",
            format_type="question",
            body=(
                "DevOps engineers: what's your CI/CD stack for Python projects in 2026? 🔧\n\n"
                "For my hackathon project I went minimal:\n"
                "→ GitHub Actions for linting + type checking\n"
                "→ pytest with pytest-asyncio for testing\n"
                "→ ruff for formatting + linting in one tool\n"
                "→ mypy for type safety\n\n"
                "The whole CI pipeline runs in under 60 seconds.\n\n"
                "Considering adding pre-commit hooks next.\n\n"
                "What's the one CI/CD tool you couldn't live without?\n\n"
                "#DevOps #CICD #Python #GitHub #SoftwareEngineering"
            ),
            hashtags=["#DevOps", "#CICD", "#Python", "#GitHub", "#SoftwareEngineering"],
        ),
        PostTemplate(
            template_id="devops_story_01",
            topic_key="cloud_devops",
            format_type="story",
            body=(
                "The deployment that taught me to always test your rollback plan: 😬\n\n"
                "I deployed a new watcher version to production.\n"
                "It crashed silently — no error, just stopped processing.\n\n"
                "My watchdog restarted it 3 times, then stopped trying.\n"
                "The Dashboard.md showed \"ERROR\" but no details.\n\n"
                "Root cause: the log directory didn't exist on the new machine.\n"
                "One missing `mkdir -p`. 3 hours of debugging.\n\n"
                "Now I always: verify vault dirs on startup, log to stderr as fallback,\n"
                "and test cold-start on a clean machine before every release.\n\n"
                "What's your most embarrassing deployment story?\n\n"
                "#DevOps #Python #Deployment #SRE #Debugging"
            ),
            hashtags=["#DevOps", "#Python", "#Deployment", "#SRE", "#Debugging"],
        ),
        PostTemplate(
            template_id="devops_announce_01",
            topic_key="cloud_devops",
            format_type="announcement",
            body=(
                "Just added Windows Task Scheduler integration to my AI Employee! ⏰\n\n"
                "The system now auto-starts on login:\n"
                "→ Orchestrator launches all watchers\n"
                "→ Content scheduler checks if a post is due\n"
                "→ Dashboard.md updates every 5 minutes\n\n"
                "No Docker. No cloud. Pure local-first automation.\n\n"
                "The task scheduler calls:\n"
                "`uv run python -m backend.orchestrator`\n\n"
                "For personal productivity tools, local-first means\n"
                "no subscriptions, no outages, no data leaks.\n\n"
                "Are you team local-first or team cloud-first for personal tools?\n\n"
                "#DevOps #Windows #Automation #LocalFirst #Python"
            ),
            hashtags=["#DevOps", "#Windows", "#Automation", "#LocalFirst", "#Python"],
        ),
        PostTemplate(
            template_id="twitter_cloud_01",
            topic_key="cloud_devops",
            format_type="twitter_short",
            body=(
                "Hot take: for personal tools, a single Python process beats Kubernetes.\n\n"
                "Simple wins. Ship faster. Debug easier.\n\n"
                "Agree? #DevOps #Python #LocalFirst"
            ),
            hashtags=["#DevOps", "#Python", "#LocalFirst"],
        ),
    ],

    "career_tips": [
        PostTemplate(
            template_id="career_tip_01",
            topic_key="career_tips",
            format_type="tip",
            body=(
                "Career tip for developers who want to grow as AI engineers: 🎯\n\n"
                "Build something real. Not a tutorial. Not a demo. Something you use daily.\n\n"
                "My Personal AI Employee project has taught me more about:\n"
                "→ System design tradeoffs\n"
                "→ Production safety requirements\n"
                "→ Human-AI interaction patterns\n\n"
                "...than any course or certification ever could.\n\n"
                "The discipline of building something production-worthy for yourself\n"
                "forces decisions that toy projects never surface.\n\n"
                "What's the most valuable real project you've built for yourself?\n\n"
                "#CareerDev #AIEngineer #SoftwareEngineering #BuildInPublic #Learning"
            ),
            hashtags=["#CareerDev", "#AIEngineer", "#SoftwareEngineering", "#BuildInPublic", "#Learning"],
        ),
        PostTemplate(
            template_id="career_insight_01",
            topic_key="career_tips",
            format_type="insight",
            body=(
                "The skill gap nobody talks about in AI engineering: 📐\n\n"
                "It's not prompt engineering. It's not fine-tuning. It's not RAG.\n\n"
                "It's system design.\n\n"
                "Most AI demos fail in production because engineers focus on the AI part\n"
                "and ignore the boring infrastructure: error handling, rate limiting,\n"
                "audit logging, rollback, human oversight.\n\n"
                "As a Senior Backend Engineer moving into agentic AI, I've found\n"
                "that classic SE skills are more valuable than ever.\n\n"
                "What skill do you think is most underrated in the AI space?\n\n"
                "#AIEngineer #CareerDev #SoftwareEngineering #Skills #BackendDev"
            ),
            hashtags=["#AIEngineer", "#CareerDev", "#SoftwareEngineering", "#Skills", "#BackendDev"],
        ),
        PostTemplate(
            template_id="career_question_01",
            topic_key="career_tips",
            format_type="question",
            body=(
                "Senior devs: what's the career advice you wish you had at year 3? 💭\n\n"
                "Mine (now that I'm deep into agentic AI): \n\n"
                "\"Invest early in systems thinking over syntax knowledge.\"\n\n"
                "I spent too long optimising for knowing more languages and frameworks.\n"
                "The real leverage came from understanding:\n"
                "→ How to decompose complex systems\n"
                "→ How to design for failure\n"
                "→ How to build trust incrementally\n\n"
                "These compound over time in ways that language expertise doesn't.\n\n"
                "#CareerDev #SoftwareEngineering #AIEngineer #Mentorship #Growth"
            ),
            hashtags=["#CareerDev", "#SoftwareEngineering", "#AIEngineer", "#Mentorship", "#Growth"],
        ),
        PostTemplate(
            template_id="career_story_01",
            topic_key="career_tips",
            format_type="story",
            body=(
                "The interview question that changed how I think about engineering: 🔄\n\n"
                "\"How would you design a system that a human can trust with their email?\"\n\n"
                "My first answer was all technology: OAuth, encryption, rate limits.\n\n"
                "The interviewer pushed back: \"What if the AI makes a mistake?\"\n\n"
                "That's when I understood the real answer:\n"
                "Design for recoverability first. Capability second.\n\n"
                "Now every system I build has an explicit \"what if this goes wrong?\" path.\n"
                "HITL, audit logs, rollback procedures — before features.\n\n"
                "What question changed your engineering philosophy?\n\n"
                "#CareerDev #SoftwareEngineering #AIEngineer #SystemDesign #Engineering"
            ),
            hashtags=["#CareerDev", "#SoftwareEngineering", "#AIEngineer", "#SystemDesign", "#Engineering"],
        ),
        PostTemplate(
            template_id="career_announce_01",
            topic_key="career_tips",
            format_type="announcement",
            body=(
                "Sharing something personal: my focus for 2026 is agentic AI systems. 🌟\n\n"
                "After years as a Senior Backend Engineer, I'm going deep on:\n"
                "→ Human-AI collaboration patterns\n"
                "→ Local-first AI architectures\n"
                "→ Practical safety for autonomous agents\n\n"
                "My hackathon project is the proof of concept.\n"
                "Building a real Personal AI Employee that handles emails,\n"
                "LinkedIn, and business operations — all with human oversight.\n\n"
                "If you're on a similar path, I'd love to connect and learn together.\n\n"
                "What's your technical focus for 2026?\n\n"
                "#CareerDev #AIEngineer #AgenticAI #Goals #SoftwareEngineering"
            ),
            hashtags=["#CareerDev", "#AIEngineer", "#AgenticAI", "#Goals", "#SoftwareEngineering"],
        ),
        PostTemplate(
            template_id="twitter_career_01",
            topic_key="career_tips",
            format_type="twitter_short",
            body=(
                "Best career move for devs in 2026: learn systems thinking.\n\n"
                "Not another framework — how to decompose, design for failure, build trust.\n\n"
                "What skill do you wish you'd learned earlier? 🎯 #CareerDev #SoftwareEngineering"
            ),
            hashtags=["#CareerDev", "#SoftwareEngineering"],
        ),
    ],
}

# Topic key normalization map (from strategy title to template key)
TOPIC_KEY_MAP: dict[str, str] = {
    "ai and automation": "ai_automation",
    "ai & automation": "ai_automation",
    "backend development": "backend_development",
    "hackathon journey": "hackathon_journey",
    "cloud & devops": "cloud_devops",
    "cloud and devops": "cloud_devops",
    "cloud devops": "cloud_devops",
    "career tips": "career_tips",
    "build in public": "hackathon_journey",
}


def normalize_topic_key(title: str) -> str:
    """Convert a topic title to a normalized template key."""
    lower = title.lower().strip()
    if lower in TOPIC_KEY_MAP:
        return TOPIC_KEY_MAP[lower]
    # Fallback: replace spaces and special chars
    return lower.replace(" ", "_").replace("&", "and").replace("-", "_")


# ── PostGenerator ─────────────────────────────────────────────────────────────


class PostGenerator:
    """Generates LinkedIn post drafts from templates."""

    def __init__(
        self,
        max_hashtags: int = 5,
        max_characters: int = MAX_CHARACTERS,
    ) -> None:
        self.max_hashtags = max_hashtags
        self.max_characters = max_characters

    def get_templates_for_topic(self, topic_key: str) -> list[PostTemplate]:
        """Return all templates for a given topic key."""
        return TEMPLATES.get(topic_key, [])

    def validate_post(self, post_text: str) -> ValidationResult:
        """Validate a post against content rules."""
        errors: list[str] = []
        char_count = len(post_text)
        hashtag_count = post_text.count("#")
        has_question = "?" in post_text

        if char_count > self.max_characters:
            errors.append(f"Character count {char_count} exceeds limit {self.max_characters}")
        if not has_question:
            errors.append("Post must contain a question")

        return ValidationResult(
            valid=len(errors) == 0,
            character_count=char_count,
            hashtag_count=hashtag_count,
            has_question=has_question,
            errors=errors,
        )

    def generate(
        self,
        topic_key: str,
        topic_title: str,
        context: PostContext | None = None,  # noqa: ARG002  # reserved for future LLM enrichment
        exclude_template_ids: list[str] | None = None,
        platform: str = "linkedin",
    ) -> GeneratedPost:
        """Generate a social media post for the given topic and platform.

        Randomly selects a template, validates character count.
        Retries up to 3 times with a different template on overflow.
        For Instagram, truncates body to INSTAGRAM_CHAR_LIMIT if exceeded.

        Args:
            topic_key: Normalized topic key (e.g. "ai_automation")
            topic_title: Human-readable topic title for logging
            context: Optional context from vault documents
            exclude_template_ids: Previously used template IDs to avoid
            platform: Target platform — "linkedin" | "facebook" | "instagram"

        Returns:
            GeneratedPost with validated body text and platform set

        Raises:
            ValueError: if no templates exist for the topic
            RuntimeError: if all templates exceed character limit after 3 retries
        """
        templates = self.get_templates_for_topic(topic_key)
        if not templates:
            logger.warning("No templates found for topic_key=%r — trying fallback", topic_key)
            # Try all available topics as fallback
            for key, tmpl_list in TEMPLATES.items():
                if tmpl_list:
                    templates = tmpl_list
                    topic_key = key
                    break
            if not templates:
                raise ValueError(f"No templates available for topic: {topic_title!r}")

        exclude = set(exclude_template_ids or [])
        available = [t for t in templates if t.template_id not in exclude]
        if not available:
            available = templates  # reset exclusions if all excluded

        max_attempts = min(3, len(available))
        shuffled = available.copy()
        random.shuffle(shuffled)

        for attempt, template in enumerate(shuffled[:max_attempts], start=1):
            body = template.body

            # Instagram: truncate if over platform limit (2200 chars)
            if platform == "instagram" and len(body) > INSTAGRAM_CHAR_LIMIT:
                suffix = "...\n[truncated to fit Instagram limit]"
                body = body[: INSTAGRAM_CHAR_LIMIT - len(suffix)] + suffix
                logger.warning(
                    "Instagram draft exceeds %d chars (%d), truncating: template=%s",
                    INSTAGRAM_CHAR_LIMIT,
                    len(template.body),
                    template.template_id,
                )

            # Twitter: emergency truncate if over 280 chars (templates should be ≤280;
            # poster hard-rejects overflows — this is the last-resort safety net)
            if platform == "twitter" and len(body) > TWITTER_CHAR_LIMIT:
                body = body[:TWITTER_CHAR_LIMIT]
                logger.warning(
                    "Twitter template exceeded %d chars, truncating: template=%s",
                    TWITTER_CHAR_LIMIT,
                    template.template_id,
                )

            validation = self.validate_post(body)

            if validation.valid:
                hashtags = template.hashtags[: self.max_hashtags]
                logger.info(
                    "Generated post: platform=%s topic=%r template=%s chars=%d (attempt %d)",
                    platform, topic_title, template.template_id, validation.character_count, attempt,
                )
                return GeneratedPost(
                    body=body,
                    hashtags=hashtags,
                    template_id=template.template_id,
                    character_count=validation.character_count,
                    topic_key=topic_key,
                    platform=platform,
                )
            else:
                logger.debug(
                    "Template %s failed validation on attempt %d: %s",
                    template.template_id, attempt, validation.errors,
                )

        raise RuntimeError(
            f"All templates for topic {topic_title!r} failed validation after {max_attempts} attempts"
        )
