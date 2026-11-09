# The most popular agent skills, 2026-11-08

Gathered for the goal of making occam ready to be widely used. What the lists show, and what occam took from them, is in [research.md](research.md#what-makes-a-skill-popular-and-the-top-100-added-2026-11-08). Popularity is adoption, not effectiveness.

Every number was read on the primary site on 2026-11-08, UTC, and none is estimated:

- **skills.sh.** The all-time leaderboard's page data at 16:26: exact install counts, which come only from `npx skills add` telemetry. Descriptions are each skill page's own, trimmed here to about 110 characters. 29 weren't fetched and are blank.
- **Claude's plugin directory.** claude.com/plugins at 16:30. Each top-50 figure matched the plugin's own page. The last column is the owner of the repository the listing points to, which for many listings is Anthropic's directory repository rather than the plugin's author.
- **GitHub stars.** The REST search API, in one pass between 16:44 and 16:45. A repository counts if it ships a `SKILL.md` for users or a `.claude-plugin/plugin.json` and is about skills or plugins. Searches can miss repositories, the category is a judgment, and "Ships hooks.json" counts any file of that name.

Counts can be inflated. A paper at [ICSE 2026](https://conf.researchr.org/details/icse-2026/icse-2026-research-track/14/Six-Million-Suspected-Fake-Stars-on-GitHub-A-Growing-Spiral-of-Popularity-Contests) estimates about 6M suspected fake GitHub stars. On skills.sh, four repositories named `*/superpowers`, unrelated to obra/superpowers, list the same four skills at 0.67M to 0.99M installs each, with 4 to 20 GitHub stars each. Bundles installed together also sit at near-identical counts: 27 Lark skills and 15 Azure skills.

## skills.sh, all time, top 100

| # | Skill | Repository | Installs | What it says it does (trimmed) |
|---:|---|---|---:|---|
| 1 | find-skills (official) | vercel-labs/skills | 4,263,180 | Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for … |
| 2 | grill-me | mattpocock/skills | 1,516,484 | A relentless interview to sharpen a plan or design. |
| 3 | hyperframes-cli | heygen-com/hyperframes | 1,470,647 | The HyperFrames CLI by job - scaffold, check, look at frames, edit the timeline, preview, render locally or … |
| 4 | hyperframes | heygen-com/hyperframes | 1,432,366 | Read first to make, edit, animate or render any video with HyperFrames (HTML rendered to video), including … |
| 5 | agent-browser (official) | vercel-labs/agent-browser | 1,432,177 | Browser automation CLI for AI agents. Use when the user needs to interact with websites, including navigating … |
| 6 | media-use | heygen-com/hyperframes | 1,342,882 | Get or make any media for a HyperFrames video - music, sound effects, images, icons, logos, voiceover, avatar … |
| 7 | design-mobile-apps | designed-by-ai/skills | 1,299,119 | Design mobile app screens with Sleek, edit Sleek projects, and implement their designs in React Native or … |
| 8 | grill-with-docs | mattpocock/skills | 1,298,980 | A relentless interview to sharpen a plan or design, which also creates docs (ADR's and glossary) as we go. |
| 9 | reddit-automation | flowkit-labs/skills | 1,296,078 | Find Reddit threads where people are genuinely asking for what you offer, then draft short, genuinely helpful … |
| 10 | improve-codebase-architecture | mattpocock/skills | 1,241,492 | Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through … |
| 11 | hyperframes-registry | heygen-com/hyperframes | 1,224,203 | About 450 ready-made HyperFrames blocks and components installed as editable source - transitions, overlays, … |
| 12 | tdd | mattpocock/skills | 1,214,521 | Test-driven development. Use when the user wants to build features or fix bugs test-first, mentions … |
| 13 | setup-matt-pocock-skills | mattpocock/skills | 1,123,720 | Configure this repo for the engineering skills: set up its issue tracker, triage label vocabulary, and domain … |
| 14 | handoff | mattpocock/skills | 1,112,250 | Compact the current conversation into a handoff document for another agent to pick up. |
| 15 | frontend-design (official) | anthropics/skills | 1,092,147 | Guidance for distinctive, intentional visual design when building new UI or reshaping an existing one. Helps … |
| 16 | grilling | mattpocock/skills | 1,073,232 | Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their … |
| 17 | ui-taste | uizze.sh | 1,056,389 | not fetched |
| 18 | prototype | mattpocock/skills | 1,054,849 | Build a throwaway prototype to answer a design question. Use when the user wants to sanity-check whether a … |
| 19 | triage | mattpocock/skills | 1,053,164 | Move issues and external PRs through a state machine of triage roles, categorise, verify, grill if needed, … |
| 20 | hyperframes-animation | heygen-com/hyperframes | 1,005,323 | All animation knowledge for HyperFrames — atomic motion rules, multi-phase scene blueprints, scene … |
| 21 | ai-video-generation | 101-skills/superpowers | 993,415 | Generate AI videos with Google Veo, Seedance 2.0, HappyHorse, Wan, Grok and 40+ models via inference.sh CLI. … |
| 22 | ai-image-generation | 101-skills/superpowers | 991,735 | Generate AI images with GPT-Image-2, FLUX, Gemini, Grok, Seedream, Reve and 50+ models via inference.sh CLI. … |
| 23 | twitter-automation | 101-skills/superpowers | 991,293 | Automate Twitter/X with posting, engagement, and user management via inference.sh CLI. Apps: x/post-tweet, … |
| 24 | ai-avatar-video | 101-skills/superpowers | 991,044 | Create AI avatar and talking head videos via inference.sh CLI. Recommended: P-Video-Avatar (fastest, … |
| 25 | domain-modeling | mattpocock/skills | 952,310 | Build and sharpen a project's domain model. Use when discussing codebase terminology, writing or editing a … |
| 26 | hyperframes-core | heygen-com/hyperframes | 931,003 | The HyperFrames composition contract — build one renderable project. Use for composition structure, the … |
| 27 | codebase-design | mattpocock/skills | 928,178 | Shared vocabulary for designing deep modules. Use when the user wants to design or improve a module's … |
| 28 | teach | mattpocock/skills | 927,972 | Teach the user a new skill or concept, within this workspace. |
| 29 | hyperframes-creative | heygen-com/hyperframes | 917,053 | Non-animation creative direction for HyperFrames videos. Use for design spec (frame.md / design.md) handling, … |
| 30 | diagnosing-bugs | mattpocock/skills | 907,300 | Diagnosis loop for hard bugs and performance regressions. Use when the user says "diagnose"/"debug this", or … |
| 31 | ai-image-generation | magentosh/superpowers | 882,180 | Generate AI images with GPT-Image-2, FLUX, Gemini, Grok, Seedream, Reve and 50+ models via inference.sh CLI. … |
| 32 | ai-video-generation | magentosh/superpowers | 881,703 | Generate AI videos with Google Veo, Seedance 2.0, HappyHorse, Wan, Grok and 40+ models via inference.sh CLI. … |
| 33 | ai-avatar-video | magentosh/superpowers | 881,588 | Create AI avatar and talking head videos via inference.sh CLI. Recommended: P-Video-Avatar (fastest, … |
| 34 | twitter-automation | magentosh/superpowers | 881,462 | Automate Twitter/X with posting, engagement, and user management via inference.sh CLI. Apps: x/post-tweet, … |
| 35 | vercel-react-best-practices (official) | vercel-labs/agent-skills | 881,110 | React and Next.js performance optimization guidelines from Vercel Engineering. This skill should be used when … |
| 36 | lark-doc | open.feishu.cn | 874,104 | not fetched |
| 37 | lark-drive | open.feishu.cn | 873,357 | not fetched |
| 38 | lark-base | open.feishu.cn | 873,324 | not fetched |
| 39 | lark-shared | open.feishu.cn | 873,214 | not fetched |
| 40 | lark-im | open.feishu.cn | 872,323 | not fetched |
| 41 | lark-calendar | open.feishu.cn | 871,912 | not fetched |
| 42 | lark-sheets | open.feishu.cn | 871,819 | not fetched |
| 43 | lark-approval | open.feishu.cn | 871,770 | not fetched |
| 44 | lark-wiki | open.feishu.cn | 871,766 | not fetched |
| 45 | lark-contact | open.feishu.cn | 870,931 | not fetched |
| 46 | lark-task | open.feishu.cn | 870,813 | not fetched |
| 47 | lark-slides | open.feishu.cn | 870,656 | not fetched |
| 48 | lark-mail | open.feishu.cn | 870,622 | not fetched |
| 49 | lark-whiteboard | open.feishu.cn | 870,459 | not fetched |
| 50 | lark-event | open.feishu.cn | 870,386 | not fetched |
| 51 | lark-openapi-explorer | open.feishu.cn | 870,136 | not fetched |
| 52 | lark-attendance | open.feishu.cn | 870,031 | not fetched |
| 53 | lark-skill-maker | open.feishu.cn | 869,644 | not fetched |
| 54 | lark-workflow-meeting-summary | open.feishu.cn | 869,502 | not fetched |
| 55 | lark-workflow-standup-report | open.feishu.cn | 869,208 | not fetched |
| 56 | lark-minutes | open.feishu.cn | 868,532 | not fetched |
| 57 | lark-vc | open.feishu.cn | 867,777 | not fetched |
| 58 | code-review | mattpocock/skills | 866,797 | Review the changes since a fixed point (commit, branch, tag, or merge-base) along two axes: Standards (does … |
| 59 | lark-okr | open.feishu.cn | 850,987 | not fetched |
| 60 | implement | mattpocock/skills | 841,748 | Implement a piece of work based on a spec or set of tickets. |
| 61 | web-design-guidelines (official) | vercel-labs/agent-skills | 838,575 | Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check … |
| 62 | lark-markdown | open.feishu.cn | 836,891 | not fetched |
| 63 | ask-matt | mattpocock/skills | 829,086 | Ask which skill or flow fits your situation. A router over the skills in this repo. |
| 64 | lark-vc-agent | open.feishu.cn | 812,387 | not fetched |
| 65 | wayfinder | mattpocock/skills | 787,150 | Plan a huge chunk of work (more than one agent session can hold) as a shared map of decision tickets on your … |
| 66 | to-spec | mattpocock/skills | 783,496 | Turn the current conversation into a spec and publish it to the project issue tracker: no interview, just … |
| 67 | lark-apps | open.feishu.cn | 782,122 | not fetched |
| 68 | research | mattpocock/skills | 780,976 | Investigate a question against high-trust primary sources and capture the findings as a Markdown file in the … |
| 69 | to-tickets | mattpocock/skills | 779,901 | Break a plan, spec, or the current conversation into a set of tracer-bullet tickets, each declaring its … |
| 70 | remotion-best-practices (official) | remotion-dev/skills | 773,382 | Router for all Remotion skills |
| 71 | ai-image-generation | skills-shell/superpowers | 763,768 | Generate AI images with GPT-Image-2, FLUX, Gemini, Grok, Seedream, Reve and 50+ models via inference.sh CLI. … |
| 72 | ai-video-generation | skills-shell/superpowers | 763,678 | Generate AI videos with Google Veo, Seedance 2.0, HappyHorse, Wan, Grok and 40+ models via inference.sh CLI. … |
| 73 | twitter-automation | skills-shell/superpowers | 763,607 | Automate Twitter/X with posting, engagement, and user management via inference.sh CLI. Apps: x/post-tweet, … |
| 74 | ai-avatar-video | skills-shell/superpowers | 763,320 | Create AI avatar and talking head videos via inference.sh CLI. Recommended: P-Video-Avatar (fastest, … |
| 75 | hyperframes-keyframes | heygen-com/hyperframes | 754,734 | Use when a HyperFrames composition needs a punch-in, punch-out, zoom, reframe, Ken Burns treatment, camera … |
| 76 | design-taste-frontend | leonxlnx/taste-skill | 748,868 | tasteskill v2, the anti-slop frontend skill. Art direction for websites, distilled from a study of 247 … |
| 77 | ai-avatar-video | qu-skills/superpowers | 674,975 | Create AI avatar and talking head videos via inference.sh CLI. Recommended: P-Video-Avatar (fastest, … |
| 78 | twitter-automation | qu-skills/superpowers | 674,542 | Automate Twitter/X with posting, engagement, and user management via inference.sh CLI. Apps: x/post-tweet, … |
| 79 | ai-video-generation | qu-skills/superpowers | 674,419 | Generate AI videos with Google Veo, Seedance 2.0, HappyHorse, Wan, Grok and 40+ models via inference.sh CLI. … |
| 80 | ai-image-generation | qu-skills/superpowers | 674,383 | Generate AI images with GPT-Image-2, FLUX, Gemini, Grok, Seedream, Reve and 50+ models via inference.sh CLI. … |
| 81 | hyperframes-audio | heygen-com/hyperframes | 663,804 | Use when audio already placed in a HyperFrames composition needs to be mixed: fade-in/fade-out, crossfade, … |
| 82 | general-video | heygen-com/hyperframes | 661,689 | Author or edit a custom HyperFrames composition when no specialized workflow fits, or when BRIEF.md sets … |
| 83 | microsoft-foundry (official) | microsoft/azure-skills | 660,019 | Build, deploy, evaluate, optimize, fine-tune, and manage Microsoft Foundry agents, models, and resources end … |
| 84 | lark-note | open.feishu.cn | 652,656 | not fetched |
| 85 | azure-diagnostics (official) | microsoft/azure-skills | 650,755 | Debug Azure production issues using AppLens, Azure Monitor, resource health, and safe triage, including … |
| 86 | azure-prepare (official) | microsoft/azure-skills | 649,856 | Prepare azd-based Azure projects for deployment: generates azure.yaml, infrastructure (Bicep/Terraform), and … |
| 87 | azure-ai (official) | microsoft/azure-skills | 649,121 | Build and troubleshoot Azure AI Search, Speech, OpenAI, and Document Intelligence apps. WHEN: AI Search, … |
| 88 | azure-deploy (official) | microsoft/azure-skills | 648,827 | Execute Azure deployments for ALREADY-PREPARED applications that have existing .azure/deployment-plan.md and … |
| 89 | azure-validate (official) | microsoft/azure-skills | 648,508 | Pre-deployment validation for Azure readiness. Run deep checks on configuration, infrastructure (Bicep or … |
| 90 | azure-storage (official) | microsoft/azure-skills | 647,653 | Azure Storage Services including Blob Storage, File Shares, Queue Storage, Table Storage, and Data Lake. … |
| 91 | azure-compliance (official) | microsoft/azure-skills | 647,256 | Run Azure compliance and security audits with azqr plus Key Vault expiration checks. Covers best-practice … |
| 92 | appinsights-instrumentation (official) | microsoft/azure-skills | 647,042 | Guidance for instrumenting webapps with Azure Application Insights. Provides telemetry patterns, SDK setup, … |
| 93 | azure-resource-lookup (official) | microsoft/azure-skills | 646,994 | List, find, and show Azure resources across subscriptions or resource groups. Handles prompts like "list the … |
| 94 | azure-resource-visualizer (official) | microsoft/azure-skills | 646,952 | Analyze Azure resource groups and generate detailed Mermaid architecture diagrams showing the relationships … |
| 95 | entra-app-registration (official) | microsoft/azure-skills | 646,919 | Guides Microsoft Entra ID app registration, OAuth 2.0 authentication, and MSAL integration. USE FOR: create … |
| 96 | azure-kusto (official) | microsoft/azure-skills | 646,655 | Query and analyze data in Azure Data Explorer (Kusto/ADX) using KQL for log analytics, telemetry, and time … |
| 97 | azure-aigateway (official) | microsoft/azure-skills | 646,256 | Configure Azure API Management as an AI Gateway for AI models, MCP tools, and agents. WHEN: semantic caching, … |
| 98 | azure-messaging (official) | microsoft/azure-skills | 637,908 | Troubleshoot and resolve issues with Azure Messaging SDKs for Event Hubs and Service Bus. Covers connection … |
| 99 | caveman | juliusbrussee/caveman | 616,229 | Terse caveman voice: answer first, fluff gone, every technical fact kept. Use for /caveman, "caveman mode", … |
| 100 | wizard | mattpocock/skills | 613,548 | Generate an interactive bash wizard that walks a human through steps only they can perform. Use when … |

## Claude plugin directory, top 50

| # | Plugin | Installs | Source repository owner |
|---:|---|---:|---|
| 1 | Frontend Design | 1,134,112 | anthropics |
| 2 | Superpowers | 1,009,371 | obra |
| 3 | Code Review | 438,525 | anthropics |
| 4 | Context7 | 417,801 | anthropics |
| 5 | Code Simplifier | 346,763 | anthropics |
| 6 | Playwright | 319,887 | anthropics |
| 7 | GitHub | 319,381 | anthropics |
| 8 | CLAUDE.md Management | 287,247 | anthropics |
| 9 | Feature Dev | 256,017 | anthropics |
| 10 | Security Guidance | 241,800 | anthropics |
| 11 | Vercel | 227,688 | vercel |
| 12 | TypeScript LSP | 212,522 | anthropics |
| 13 | Ralph Loop | 196,527 | anthropics |
| 14 | Claude Code Setup | 195,067 | anthropics |
| 15 | Commit Commands | 171,244 | anthropics |
| 16 | Figma | 167,556 | Figma |
| 17 | Supabase | 118,617 | supabase-community |
| 18 | PR Review Toolkit | 114,856 | anthropics |
| 19 | Pyright LSP | 109,778 | anthropics |
| 20 | Chrome DevTools | 102,569 | Google |
| 21 | Telegram | 100,332 | anthropics |
| 22 | Atlassian MCP | 92,289 | atlassian |
| 23 | Slack | 92,287 | slackapi |
| 24 | Serena | 89,147 | anthropics |
| 25 | Plugin Developer Toolkit | 67,663 | anthropics |
| 26 | Agent SDK Dev | 66,631 | anthropics |
| 27 | Explanatory Output Style | 64,377 | anthropics |
| 28 | Playground | 64,198 | anthropics |
| 29 | Stripe | 61,066 | stripe |
| 30 | Hookify | 60,376 | anthropics |
| 31 | Greptile | 56,611 | greptileai |
| 32 | Remember | 51,442 | Digital Process Tools |
| 33 | Linear | 48,038 | anthropics |
| 34 | C# LSP | 43,741 | anthropics |
| 35 | Learning Output Style | 42,241 | anthropics |
| 36 | Go LSP (gopls) | 41,639 | anthropics |
| 37 | GitLab | 40,805 | anthropics |
| 38 | Firecrawl | 39,279 | firecrawl |
| 39 | Sentry | 38,810 | getsentry |
| 40 | Rust Analyzer LSP | 35,933 | anthropics |
| 41 | Hugging Face Skills | 34,575 | huggingface |
| 42 | MCP Server Dev | 33,959 | anthropics |
| 43 | Java LSP (Eclipse JDT.LS) | 33,734 | anthropics |
| 44 | PHP LSP | 32,856 | anthropics |
| 45 | CodeRabbit | 32,361 | coderabbitai |
| 46 | Discord | 32,323 | anthropics |
| 47 | Clangd LSP | 29,851 | anthropics |
| 48 | Microsoft Docs | 26,765 | microsoftdocs |
| 49 | Firebase | 26,168 | anthropics |
| 50 | Kotlin LSP | 24,127 | anthropics |

## GitHub stars, top 100 repositories that ship skills or a plugin

| # | Repository | Stars | Category | Ships hooks.json |
|---:|---|---:|---|---|
| 1 | [morluto/rea](https://github.com/morluto/rea) | 442,933 | security | no |
| 2 | [mattpocock/skills](https://github.com/mattpocock/skills) | 318,305 | workflow/process | no |
| 3 | [obra/superpowers](https://github.com/obra/superpowers) | 314,454 | workflow/process | yes (1) |
| 4 | [affaan-m/ECC](https://github.com/affaan-m/ECC) | 299,525 | workflow/process | yes (4) |
| 5 | [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | 230,837 | code quality/review | no |
| 6 | [anthropics/skills](https://github.com/anthropics/skills) | 189,325 | other | no |
| 7 | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) | 186,767 | code quality/review | no |
| 8 | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 146,811 | frontend/design | no |
| 9 | [garrytan/gstack](https://github.com/garrytan/gstack) | 140,745 | workflow/process | no |
| 10 | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) | 118,303 | persona/style | yes (1) |
| 11 | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | 114,766 | memory/context | yes (3) |
| 12 | [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) | 114,043 | workflow/process | no |
| 13 | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | 111,925 | frontend/design | no |
| 14 | [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach) | 110,226 | other | no |
| 15 | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | 106,000 | frontend/design | yes (4) |
| 16 | [tt-a1i/archify](https://github.com/tt-a1i/archify) | 94,656 | frontend/design | no |
| 17 | [Egonex-AI/Understand-Anything](https://github.com/Egonex-AI/Understand-Anything) | 91,438 | memory/context | yes (1) |
| 18 | [ruvnet/ruflo](https://github.com/ruvnet/ruflo) | 81,238 | workflow/process | yes (50) |
| 19 | [career-ops-hq/career-ops](https://github.com/career-ops-hq/career-ops) | 81,116 | other | yes (1) |
| 20 | [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) | 80,927 | other | yes (1) |
| 21 | [ComposioHQ/awesome-claude-skills](https://github.com/ComposioHQ/awesome-claude-skills) | 79,046 | other | no |
| 22 | [OpenMontageInc/OpenMontage](https://github.com/OpenMontageInc/OpenMontage) | 78,559 | other | no |
| 23 | [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master) | 74,860 | office/docs files | no |
| 24 | [ai-job-search-dev/ai-job-search](https://github.com/ai-job-search-dev/ai-job-search) | 70,447 | other | no |
| 25 | [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) | 67,001 | other | no |
| 26 | [cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill) | 66,529 | security | no |
| 27 | [blader/humanizer](https://github.com/blader/humanizer) | 66,294 | docs/writing | no |
| 28 | [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design) | 65,818 | frontend/design | no |
| 29 | [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd) | 60,505 | persona/style | yes (1) |
| 30 | [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) | 59,181 | other | no |
| 31 | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills) | 56,473 | other | no |
| 32 | [Imbad0202/academic-research-skills](https://github.com/Imbad0202/academic-research-skills) | 55,865 | docs/writing | yes (1) |
| 33 | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) | 55,124 | workflow/process | no |
| 34 | [emilkowalski/skills](https://github.com/emilkowalski/skills) | 54,667 | frontend/design | no |
| 35 | [Yuan1z0825/nature-skills](https://github.com/Yuan1z0825/nature-skills) | 52,757 | docs/writing | no |
| 36 | [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) | 51,008 | other | no |
| 37 | [Nutlope/hallmark](https://github.com/Nutlope/hallmark) | 50,737 | frontend/design | no |
| 38 | [alibaba/open-code-review](https://github.com/alibaba/open-code-review) | 49,648 | code quality/review | no |
| 39 | [sickn33/agentic-awesome-skills](https://github.com/sickn33/agentic-awesome-skills) | 49,364 | other | no |
| 40 | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | 46,435 | other | yes (7) |
| 41 | [zhaoxuya520/reverse-skill](https://github.com/zhaoxuya520/reverse-skill) | 44,308 | security | no |
| 42 | [wshobson/agents](https://github.com/wshobson/agents) | 42,305 | other | yes (2) |
| 43 | [anthropics/financial-services](https://github.com/anthropics/financial-services) | 41,140 | other | yes (4) |
| 44 | [github/awesome-copilot](https://github.com/github/awesome-copilot) | 40,925 | other | yes (8) |
| 45 | [Yeachan-Heo/oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) | 40,687 | workflow/process | yes (2) |
| 46 | [JCodesMore/ai-website-cloner-template](https://github.com/JCodesMore/ai-website-cloner-template) | 38,851 | frontend/design | no |
| 47 | [vercel-labs/skills](https://github.com/vercel-labs/skills) | 38,582 | meta/skill-making | no |
| 48 | [alchaincyf/nuwa-skill](https://github.com/alchaincyf/nuwa-skill) | 37,806 | persona/style | no |
| 49 | [virgiliojr94/book-to-skill](https://github.com/virgiliojr94/book-to-skill) | 37,315 | meta/skill-making | no |
| 50 | [Donchitos/Claude-Code-Game-Studios](https://github.com/Donchitos/Claude-Code-Game-Studios) | 36,864 | other | no |
| 51 | [mukul975/Anthropic-Cybersecurity-Skills](https://github.com/mukul975/Anthropic-Cybersecurity-Skills) | 35,786 | security | no |
| 52 | [freestylefly/awesome-gpt-image-2](https://github.com/freestylefly/awesome-gpt-image-2) | 35,586 | other | no |
| 53 | [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins) | 35,193 | other | no |
| 54 | [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) | 34,974 | code quality/review | yes (1) |
| 55 | [Yeachan-Heo/oh-my-codex](https://github.com/Yeachan-Heo/oh-my-codex) | 33,743 | workflow/process | yes (1) |
| 56 | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | 33,714 | language/framework | no |
| 57 | [mksglu/context-mode](https://github.com/mksglu/context-mode) | 33,685 | memory/context | yes (4) |
| 58 | [davila7/claude-code-templates](https://github.com/davila7/claude-code-templates) | 33,210 | other | yes (52) |
| 59 | [iOfficeAI/OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) | 33,140 | office/docs files | no |
| 60 | [tirth8205/code-review-graph](https://github.com/tirth8205/code-review-graph) | 32,642 | memory/context | yes (1) |
| 61 | [googleworkspace/cli](https://github.com/googleworkspace/cli) | 32,180 | other | no |
| 62 | [zarazhangrui/frontend-slides](https://github.com/zarazhangrui/frontend-slides) | 32,075 | office/docs files | no |
| 63 | [browser-use/video-use](https://github.com/browser-use/video-use) | 30,748 | other | no |
| 64 | [rohitg00/agentmemory](https://github.com/rohitg00/agentmemory) | 30,203 | memory/context | yes (3) |
| 65 | [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) | 29,476 | other | yes (8) |
| 66 | [op7418/guizang-ppt-skill](https://github.com/op7418/guizang-ppt-skill) | 29,475 | office/docs files | no |
| 67 | [jarrodwatts/claude-hud](https://github.com/jarrodwatts/claude-hud) | 29,133 | other | no |
| 68 | [alchaincyf/huashu-design](https://github.com/alchaincyf/huashu-design) | 28,973 | frontend/design | no |
| 69 | [openai/skills](https://github.com/openai/skills) | 28,597 | other | no |
| 70 | [gastownhall/beads](https://github.com/gastownhall/beads) | 28,593 | memory/context | yes (1) |
| 71 | [hypit-ai/hypit](https://github.com/hypit-ai/hypit) | 28,579 | other | no |
| 72 | [eyaltoledano/claude-task-master](https://github.com/eyaltoledano/claude-task-master) | 28,326 | workflow/process | no |
| 73 | [OthmanAdi/planning-with-files](https://github.com/OthmanAdi/planning-with-files) | 27,951 | workflow/process | yes (4) |
| 74 | [phuryn/pm-skills](https://github.com/phuryn/pm-skills) | 27,773 | other | no |
| 75 | [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo) | 27,415 | other | yes (1) |
| 76 | [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills) | 27,389 | other | no |
| 77 | [titanwings/distilly](https://github.com/titanwings/distilly) | 26,444 | persona/style | no |
| 78 | [VoltAgent/awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents) | 26,419 | other | no |
| 79 | [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin) | 25,985 | workflow/process | yes (3) |
| 80 | [wheresryan22/anatomy](https://github.com/wheresryan22/anatomy) | 25,955 | frontend/design | no |
| 81 | [NVIDIA/SkillSpector](https://github.com/NVIDIA/SkillSpector) | 24,887 | security | no |
| 82 | [SuperClaude-Org/SuperClaude_Framework](https://github.com/SuperClaude-Org/SuperClaude_Framework) | 23,931 | workflow/process | yes (2) |
| 83 | [google/skills](https://github.com/google/skills) | 23,671 | language/framework | no |
| 84 | [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) | 22,274 | docs/writing | no |
| 85 | [snarktank/ralph](https://github.com/snarktank/ralph) | 22,159 | workflow/process | no |
| 86 | [KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills) | 22,066 | other | no |
| 87 | [img2threejs/img2threejs](https://github.com/img2threejs/img2threejs) | 20,898 | other | no |
| 88 | [latent-spaces/brag](https://github.com/latent-spaces/brag) | 20,736 | docs/writing | no |
| 89 | [bradautomates/claude-video](https://github.com/bradautomates/claude-video) | 20,205 | other | yes (1) |
| 90 | [teng-lin/notebooklm-py](https://github.com/teng-lin/notebooklm-py) | 20,171 | other | no |
| 91 | [tanweai/pua](https://github.com/tanweai/pua) | 19,818 | persona/style | yes (1) |
| 92 | [browser-use/browser-harness](https://github.com/browser-use/browser-harness) | 18,953 | other | no |
| 93 | [microsoft/SkillOpt](https://github.com/microsoft/SkillOpt) | 18,945 | meta/skill-making | yes (1) |
| 94 | [wanshuiyin/Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep) | 18,874 | other | no |
| 95 | [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop) | 18,737 | docs/writing | no |
| 96 | [muratcankoylan/Agent-Skills-for-Context-Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering) | 18,320 | memory/context | no |
| 97 | [greensock/gsap-skills](https://github.com/greensock/gsap-skills) | 18,107 | language/framework | no |
| 98 | [larksuite/cli](https://github.com/larksuite/cli) | 18,019 | other | no |
| 99 | [Vincentwei1021/video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) | 17,832 | other | no |
| 100 | [composio-community/awesome-codex-skills](https://github.com/composio-community/awesome-codex-skills) | 17,255 | other | no |
