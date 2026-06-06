---
name: list-templates
description: List available sandbox templates
---

# /list-sandbox-templates Command

Lists all available Bumba Sandbox templates including official Bumba Sandbox templates, custom team templates created from snapshots, and community templates. Supports filtering, search, and detailed template information to help users choose the right starting point for new sandboxes.

## Usage

```
/list-sandbox-templates [options]
```

## Parameters

- `--filter <category>` (optional): Filter by category (official, custom, community, all) - default: all
- `--search <query>` (optional): Search templates by name or description
- `--language <lang>` (optional): Filter by programming language (node, python, go, rust, java, etc.)
- `--sort <field>` (optional): Sort by field (name, created, size, popular) - default: popular
- `--details` (optional): Show detailed information for each template - default: false
- `--tag <tag>` (optional): Filter by tag (web, api, ml, data, etc.)
- `--show-deprecated` (optional): Include deprecated templates - default: false

## Workflow

### Step 1: Template Discovery

```
📋 List Available Sandbox Templates
═══════════════════════════════════════════════

Loading templates...
  ✓ Official Bumba Sandbox templates: 24
  ✓ Custom team templates: 8
  ✓ Community templates: 142
  ✓ Total: 174 templates

Applying filters:
  Category: all
  Language: (all)
  Tags: (none)
  Search: (none)

Sorting by: popular (most used first)

───────────────────────────────────────────────
```

### Step 2: Template List Display

```
Available Templates (174 total)

━━━ Official Bumba Sandbox Templates (24) ━━━

1. node18-typescript
   Description: Node.js 18 with TypeScript, ESLint, Prettier
   Language: JavaScript/TypeScript
   Size: 1.2 GB
   Tools: npm, yarn, pnpm, git, Docker
   Use Cases: Web apps, APIs, microservices
   Popular: ★★★★★ (12,450 uses)
   Created: 2024-03-15
   Status: ✓ Active

2. python3.11-ml
   Description: Python 3.11 with ML/Data Science stack
   Language: Python
   Size: 3.8 GB
   Tools: pip, conda, jupyter, git
   Libraries: numpy, pandas, scikit-learn, torch, tensorflow
   Use Cases: Machine learning, data analysis
   Popular: ★★★★★ (8,230 uses)
   Created: 2024-04-01
   Status: ✓ Active

3. go1.21
   Description: Go 1.21 with common tools
   Language: Go
   Size: 890 MB
   Tools: go, gofmt, golint, git, Docker
   Use Cases: Backend services, CLIs, microservices
   Popular: ★★★★☆ (5,120 uses)
   Created: 2024-05-10
   Status: ✓ Active

4. rust-stable
   Description: Rust stable with cargo, clippy
   Language: Rust
   Size: 1.5 GB
   Tools: cargo, rustc, clippy, rustfmt, git
   Use Cases: Systems programming, WebAssembly
   Popular: ★★★★☆ (3,890 uses)
   Created: 2024-06-01
   Status: ✓ Active

5. java17-gradle
   Description: Java 17 with Gradle build tool
   Language: Java
   Size: 2.1 GB
   Tools: java, gradle, git, Maven
   Use Cases: Enterprise apps, Spring Boot, Android
   Popular: ★★★☆☆ (2,450 uses)
   Created: 2024-03-20
   Status: ✓ Active

... (19 more official templates)

━━━ Custom Team Templates (8) ━━━

26. oauth-starter-template
    Description: Pre-configured OAuth integration starter
    Language: JavaScript/TypeScript
    Size: 1.1 GB
    Base: node18-typescript
    Created: 2025-01-18 by @lead-developer
    Features:
      ✓ OAuth 2.0 setup (Google, GitHub, Auth0)
      ✓ User authentication flow
      ✓ JWT token management
      ✓ Test suite with 100% coverage
    Use Cases: Apps requiring OAuth authentication
    Popular: ★★★☆☆ (42 uses within team)
    Status: ✓ Active

27. payment-integration-starter
    Description: Stripe + PayPal payment integration
    Language: JavaScript/TypeScript
    Size: 1.3 GB
    Base: node18-typescript
    Created: 2025-01-15 by @backend-team
    Features:
      ✓ Stripe API integration
      ✓ PayPal SDK setup
      ✓ Webhook handlers
      ✓ Payment test utilities
    Use Cases: E-commerce, subscription services
    Popular: ★★★☆☆ (38 uses within team)
    Status: ✓ Active

... (6 more custom templates)

━━━ Community Templates (142) ━━━

34. nextjs13-app-starter
    Description: Next.js 13 with App Router, Tailwind CSS
    Language: JavaScript/TypeScript
    Size: 1.4 GB
    Base: node18-typescript
    Author: @nextjs-community
    Features:
      ✓ Next.js 13 App Router
      ✓ Tailwind CSS configured
      ✓ ESLint + Prettier
      ✓ TypeScript strict mode
    Use Cases: Modern web applications
    Popular: ★★★★★ (4,230 uses)
    Status: ✓ Active

35. django-rest-api
    Description: Django REST Framework starter
    Language: Python
    Size: 1.8 GB
    Base: python3.11
    Author: @django-community
    Features:
      ✓ Django 4.2 + DRF
      ✓ PostgreSQL configured
      ✓ JWT authentication
      ✓ API documentation (Swagger)
    Use Cases: RESTful APIs, backends
    Popular: ★★★★☆ (3,120 uses)
    Status: ✓ Active

... (140 more community templates)

───────────────────────────────────────────────

Summary:
  Official: 24 templates (Bumba Sandbox maintained)
  Custom: 8 templates (your team)
  Community: 142 templates (verified contributors)

Quick Actions:
  Create sandbox: /create-sandbox --template <template_id>
  View details: /list-sandbox-templates --details
  Filter by language: /list-sandbox-templates --language python
  Search: /list-sandbox-templates --search "oauth"

───────────────────────────────────────────────
```

## Examples

### Example 1: List All Templates (Default)

```
/list-sandbox-templates
```

**Output**:
```
📋 Sandbox Templates (174 total)

━━━ Popular Templates ━━━
1. node18-typescript (★★★★★ 12.4k uses)
2. python3.11-ml (★★★★★ 8.2k uses)
3. go1.21 (★★★★☆ 5.1k uses)
4. nextjs13-app-starter (★★★★★ 4.2k uses)
5. rust-stable (★★★★☆ 3.9k uses)
... (169 more)

Categories:
  Official: 24
  Custom: 8
  Community: 142

Filter: /list-sandbox-templates --filter official
Details: /list-sandbox-templates --details
```

### Example 2: Filter by Official Templates Only

```
/list-sandbox-templates --filter official
```

**Output**:
```
📋 Official Bumba Sandbox Templates (24)

━━━ JavaScript/TypeScript ━━━
1. node18-typescript - Node.js 18 + TypeScript (1.2 GB)
2. node20-latest - Node.js 20 latest (1.1 GB)
3. deno-latest - Deno runtime (780 MB)
4. bun-latest - Bun runtime (650 MB)

━━━ Python ━━━
5. python3.11 - Python 3.11 base (1.4 GB)
6. python3.11-ml - Python 3.11 + ML stack (3.8 GB)
7. python3.10 - Python 3.10 base (1.3 GB)

━━━ Go ━━━
8. go1.21 - Go 1.21 (890 MB)
9. go1.20 - Go 1.20 (870 MB)

━━━ Rust ━━━
10. rust-stable - Rust stable (1.5 GB)
11. rust-nightly - Rust nightly (1.6 GB)

... (14 more)

All official templates include: git, Docker, common CLI tools
Create: /create-sandbox --template <name>
```

### Example 3: Search for OAuth Templates

```
/list-sandbox-templates --search oauth
```

**Output**:
```
📋 Search Results: "oauth" (5 matches)

1. oauth-starter-template (Custom)
   Pre-configured OAuth integration starter
   Language: TypeScript
   Features: OAuth 2.0, JWT, Google/GitHub
   Size: 1.1 GB
   Uses: 42 (team)

2. nextjs-oauth-template (Community)
   Next.js with OAuth authentication
   Author: @nextjs-community
   Features: NextAuth.js, OAuth providers
   Size: 1.3 GB
   Uses: 890

3. express-oauth2-server (Community)
   Express.js OAuth2 server implementation
   Author: @oauth-community
   Features: OAuth2 server, authorization codes
   Size: 980 MB
   Uses: 420

4. django-oauth-toolkit (Community)
   Django OAuth Toolkit starter
   Author: @django-community
   Features: OAuth2 provider, client apps
   Size: 1.7 GB
   Uses: 310

5. spring-oauth2-resource (Community)
   Spring Boot OAuth2 resource server
   Author: @spring-community
   Features: OAuth2 resource server, JWT
   Size: 2.3 GB
   Uses: 245

Create: /create-sandbox --template <template_name>
```

### Example 4: Filter by Programming Language

```
/list-sandbox-templates --language python
```

**Output**:
```
📋 Python Templates (34 total)

━━━ Official (3) ━━━
1. python3.11 - Python 3.11 base (1.4 GB)
2. python3.11-ml - Python 3.11 + ML/Data Science (3.8 GB)
3. python3.10 - Python 3.10 base (1.3 GB)

━━━ Community (31) ━━━
4. django-rest-api - Django REST Framework (1.8 GB)
5. fastapi-starter - FastAPI with async support (1.2 GB)
6. flask-api-starter - Flask REST API (980 MB)
7. pytorch-deep-learning - PyTorch + CUDA (5.2 GB)
8. tensorflow-ml - TensorFlow 2.x (4.8 GB)
9. data-science-notebook - Jupyter + pandas/numpy (2.4 GB)
10. scrapy-crawler - Web scraping with Scrapy (1.1 GB)
... (24 more)

Create: /create-sandbox --template <name>
```

### Example 5: Show Detailed Information

```
/list-sandbox-templates --filter official --details
```

**Output**:
```
📋 Official Templates (Detailed)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Template: node18-typescript
ID: tmpl_node18_typescript_v1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Description:
  Node.js 18 LTS with TypeScript, ESLint, Prettier
  Pre-configured for modern web development

Language: JavaScript/TypeScript
Category: Official Bumba Sandbox
Version: 1.2.0
Created: 2024-03-15
Last Updated: 2025-01-10
Status: ✓ Active

Size: 1.2 GB
  node_modules: 680 MB
  System: 420 MB
  Tools: 100 MB

Installed Tools:
  • Node.js: v18.17.0 LTS
  • npm: 9.8.1
  • yarn: 1.22.19
  • pnpm: 8.6.0
  • TypeScript: 5.2.2
  • ESLint: 8.48.0
  • Prettier: 3.0.3
  • Jest: 29.6.4
  • git: 2.41.0
  • Docker: 24.0.5

Pre-installed Libraries:
  • express: 4.18.2
  • axios: 1.5.0
  • lodash: 4.17.21
  • date-fns: 2.30.0
  • zod: 3.22.2

Configuration:
  ✓ TypeScript strict mode
  ✓ ESLint recommended rules
  ✓ Prettier formatting
  ✓ Git hooks (husky)
  ✓ Jest configured

Use Cases:
  • Web applications (Express, Next.js, etc.)
  • RESTful APIs
  • Microservices
  • CLI tools
  • Backend services

Performance:
  Boot Time: ~8 seconds
  Memory: 512 MB base, 4 GB limit
  CPU: 2 vCPU

Popular: ★★★★★ (12,450 uses)
Rating: 4.8/5.0 (1,240 reviews)

Create Sandbox:
  /create-sandbox --template node18-typescript

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Template: python3.11-ml
ID: tmpl_python311_ml_v2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Description:
  Python 3.11 with comprehensive ML/Data Science stack
  Includes PyTorch, TensorFlow, scikit-learn, pandas

Language: Python
Category: Official E2B
Version: 2.1.0
Created: 2024-04-01
Last Updated: 2025-01-12
Status: ✓ Active

Size: 3.8 GB
  Python packages: 2.4 GB
  System: 1.2 GB
  CUDA libraries: 200 MB

Installed Tools:
  • Python: 3.11.6
  • pip: 23.2.1
  • conda: 23.7.4
  • Jupyter: 1.0.0
  • git: 2.41.0
  • CUDA: 12.1 (for GPU support)

Pre-installed Libraries:
  ML/Deep Learning:
    • torch: 2.0.1
    • tensorflow: 2.13.0
    • scikit-learn: 1.3.0
    • keras: 2.13.1

  Data Processing:
    • numpy: 1.24.3
    • pandas: 2.0.3
    • polars: 0.18.15

  Visualization:
    • matplotlib: 3.7.2
    • seaborn: 0.12.2
    • plotly: 5.16.1

  Other:
    • opencv-python: 4.8.0
    • pillow: 10.0.0
    • requests: 2.31.0

Configuration:
  ✓ Jupyter notebook server ready
  ✓ GPU support (CUDA 12.1)
  ✓ Virtual environment (conda)
  ✓ IPython enhanced shell

Use Cases:
  • Machine learning model training
  • Data analysis and exploration
  • Computer vision projects
  • Natural language processing
  • Statistical analysis
  • Research and experimentation

Performance:
  Boot Time: ~15 seconds
  Memory: 2 GB base, 16 GB limit
  CPU: 4 vCPU
  GPU: Optional (NVIDIA T4/V100)

Popular: ★★★★★ (8,230 uses)
Rating: 4.7/5.0 (820 reviews)

Create Sandbox:
  /create-sandbox --template python3.11-ml

... (22 more detailed templates)
```

### Example 6: Filter by Tags

```
/list-sandbox-templates --tag web
```

**Output**:
```
📋 Templates Tagged: "web" (42 matches)

1. node18-typescript (Official)
   Node.js 18 with TypeScript
   Tags: #web #api #backend #typescript
   Size: 1.2 GB
   Uses: 12.4k

2. nextjs13-app-starter (Community)
   Next.js 13 with App Router
   Tags: #web #frontend #react #nextjs
   Size: 1.4 GB
   Uses: 4.2k

3. django-web-app (Community)
   Django full-stack web framework
   Tags: #web #python #fullstack #django
   Size: 2.1 GB
   Uses: 2.8k

4. ruby-rails7 (Official)
   Ruby on Rails 7 web framework
   Tags: #web #ruby #rails #fullstack
   Size: 1.9 GB
   Uses: 1.5k

... (38 more web templates)

Other Tags:
  #api (68 templates)
  #backend (54 templates)
  #frontend (32 templates)
  #fullstack (28 templates)

Browse: /list-sandbox-templates --tag <tag_name>
```

### Example 7: Sort by Recently Created

```
/list-sandbox-templates --sort created
```

**Output**:
```
📋 Templates (Newest First)

Recent Templates:
1. bun-latest (Official) - Created 2025-01-15
   Bun JavaScript runtime
   Size: 650 MB
   🆕 New

2. oauth-starter-template (Custom) - Created 2025-01-18
   OAuth integration starter
   Size: 1.1 GB
   🆕 New

3. astro-ssr-starter (Community) - Created 2025-01-12
   Astro with SSR enabled
   Size: 890 MB
   🆕 New

4. go1.22-beta (Official) - Created 2025-01-08
   Go 1.22 beta release
   Size: 920 MB

5. sveltekit-starter (Community) - Created 2025-01-05
   SvelteKit full-stack
   Size: 780 MB

... (169 more, oldest first)

Sort Options:
  --sort popular (default)
  --sort created (newest first)
  --sort name (alphabetical)
  --sort size (smallest first)
```

### Example 8: Show Custom Team Templates Only

```
/list-sandbox-templates --filter custom
```

**Output**:
```
📋 Custom Team Templates (8)

1. oauth-starter-template
   Created: 2025-01-18 by @lead-developer
   Description: Pre-configured OAuth integration
   Base: node18-typescript
   Size: 1.1 GB
   Uses: 42 (team)
   Features:
     ✓ OAuth 2.0 (Google, GitHub, Auth0)
     ✓ JWT authentication
     ✓ 100% test coverage

2. payment-integration-starter
   Created: 2025-01-15 by @backend-team
   Description: Stripe + PayPal integration
   Base: node18-typescript
   Size: 1.3 GB
   Uses: 38 (team)
   Features:
     ✓ Stripe API
     ✓ PayPal SDK
     ✓ Webhook handlers

3. microservices-template
   Created: 2025-01-10 by @backend-team
   Description: Microservices architecture starter
   Base: node18-typescript
   Size: 1.5 GB
   Uses: 28 (team)
   Features:
     ✓ Express.js services
     ✓ gRPC communication
     ✓ Docker Compose setup

... (5 more custom templates)

Create New Template:
  /sandbox-snapshot <sandbox_id> --template --name "my-template"

Use Template:
  /create-sandbox --template <template_name>
```

## Error Handling

### Error 1: No Templates Found

```
❌ Error: No templates match your criteria

Filters Applied:
  Language: brainfuck
  Category: official
  Tag: (none)

No official templates found for language "brainfuck".

Available Languages:
  JavaScript/TypeScript (node, deno, bun)
  Python (python)
  Go (go)
  Rust (rust)
  Java (java)
  Ruby (ruby)
  PHP (php)
  C/C++ (cpp)
  ... (12 more)

Suggestions:

  View all templates:
    /list-sandbox-templates

  View available languages:
    /list-sandbox-templates --languages

  Search by name:
    /list-sandbox-templates --search "your-query"
```

### Error 2: Invalid Filter

```
❌ Error: Invalid filter

Filter: super-official
Valid Filters: official, custom, community, all

Valid filter values:
  official   - E2B maintained templates
  custom     - Your team's custom templates
  community  - Community contributed templates
  all        - All templates (default)

Usage:
  /list-sandbox-templates --filter official
  /list-sandbox-templates --filter custom
  /list-sandbox-templates --filter community
```

### Error 3: Network Error

```
❌ Error: Failed to load templates

Reason: Network timeout connecting to E2B registry

Could not retrieve template list from E2B servers.

Cached Templates (48 hours old):
  ⚠️ Showing cached results (may be outdated)

  1. node18-typescript (cached)
  2. python3.11-ml (cached)
  3. go1.21 (cached)
  ... (21 more cached)

Recovery Options:

  Option 1: Retry Connection
  ───────────────────────────────────────
    /list-sandbox-templates --refresh

  Forces refresh from server

  Option 2: Use Cached Results
  ───────────────────────────────────────
    Continue with cached templates
    May miss recent additions

  Option 3: Check Network
  ───────────────────────────────────────
    ping registry.e2b.dev
    Check internet connectivity

Recommendation: Try Option 1 to refresh
```

### Error 4: Deprecated Templates Warning

```
⚠️ Warning: Some results include deprecated templates

Deprecated Templates (Hidden by Default):

  node16-typescript (deprecated 2024-11-01)
    Reason: Node.js 16 reached EOL
    Replacement: node18-typescript or node20-latest

  python3.9 (deprecated 2024-12-15)
    Reason: Python 3.9 security updates ending
    Replacement: python3.11 or python3.10

Show deprecated templates:
  /list-sandbox-templates --show-deprecated

Recommendation: Use actively maintained templates
```

### Error 5: Rate Limit Exceeded

```
❌ Error: Rate limit exceeded

You have exceeded the template list request limit.

Current Usage:
  Requests: 100 / 100 (per hour)
  Reset In: 42 minutes

Rate limits protect service availability.

Recovery Options:

  Option 1: Wait for Reset
  ───────────────────────────────────────
    Wait 42 minutes for limit to reset
    Then retry request

  Option 2: Use Cached Results
  ───────────────────────────────────────
    /list-sandbox-templates --cache-only

  Uses locally cached template list
  No network request required

Recommendation: Option 2 for immediate access
```

## Integration

### Integration with Template Registry
- Fetches templates from E2B template registry
- Caches template list locally (48 hours)
- Validates template availability
- Tracks template usage statistics
- Manages template metadata

### Integration with Sandbox Creation
- Provides template IDs for /create-sandbox command
- Validates template compatibility
- Supports template-based sandbox provisioning
- Enables quick sandbox creation from templates

### Integration with Snapshot System
- Lists custom templates created from snapshots
- Shows snapshot-based template metadata
- Enables template creation workflow
- Tracks template lineage

### Integration with Search System
- Full-text search across template names and descriptions
- Tag-based filtering
- Language-based filtering
- Sorting and ranking

### Integration with Team Management
- Shows team-specific custom templates
- Tracks template creators
- Manages template permissions
- Enables team template sharing

## Use Cases

### Use Case 1: Find Node.js Template
**Scenario**: Need a Node.js template for new API project.

**Command**:
```bash
/list-sandbox-templates --language node --tag api
```

**Result**: List of Node.js templates suitable for API development.

### Use Case 2: Browse Team Templates
**Scenario**: See what templates team has created.

**Command**:
```bash
/list-sandbox-templates --filter custom
```

**Result**: List of 8 custom team templates with details.

### Use Case 3: Search for OAuth Templates
**Scenario**: Need template with OAuth pre-configured.

**Command**:
```bash
/list-sandbox-templates --search oauth
```

**Result**: 5 templates with OAuth integration.

### Use Case 4: Find ML Template
**Scenario**: Need Python template for machine learning project.

**Command**:
```bash
/list-sandbox-templates --language python --tag ml
```

**Result**: Python ML templates including python3.11-ml.

### Use Case 5: View Template Details
**Scenario**: Need detailed info before choosing template.

**Command**:
```bash
/list-sandbox-templates --filter official --details
```

**Result**: Comprehensive details for all official templates.

## Performance Considerations

### List Speed
- Cached results: <100ms
- Network fetch: 1-3 seconds
- Detailed mode: +500ms per template
- Search/filter: <200ms

### Caching
- Cache duration: 48 hours
- Cache size: <2 MB
- Refresh: Manual or automatic
- Cache location: Local filesystem

### Network Usage
- Initial fetch: ~500 KB
- Subsequent: ~50 KB (if-modified-since)
- Images: Not downloaded unless viewed
- Bandwidth: Minimal

## Notes

- **Official Templates**: Maintained and updated by E2B team
- **Custom Templates**: Created by your team from snapshots
- **Community Templates**: Verified community contributions
- **Caching**: Results cached 48 hours for performance
- **Search**: Full-text search across names and descriptions
- **Filtering**: Multiple filter options for precise results
- **Sorting**: Sort by popularity, date, name, or size
- **Details Mode**: Comprehensive information for each template
- **Deprecated**: Hidden by default, show with `--show-deprecated`
- **Tags**: Organize templates by use case
- **Ratings**: Community ratings for popular templates
- **Create**: Use template with `/create-sandbox --template <id>`
