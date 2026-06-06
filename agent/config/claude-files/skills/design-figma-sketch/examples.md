# Design Figma Sketch - Examples

## Example 1: Starting a session

**User:** `/design-figma-sketch`

**Assistant:**
1. Checks if WebSocket server is running on port 3055
2. Checks if design-bridge server is running on ports 9001/9002
3. Starts any missing servers
4. Asks: "What's your current Figma channel ID from the CREATE tab?"
5. User provides: "G2K7NY"
6. Joins channel G2K7NY
7. Loads THEME.js
8. Starts listening with `wait_for_prompt`

## Example 2: Processing design requests

**Figma plugin message:** "create a blue button"

**Assistant:**
1. Receives message via `wait_for_prompt`
2. Creates button using BUMBA blue (#3600aa) from THEME.js
3. Applies proper spacing and border radius from tokens
4. Uses Apertura font for button text
5. Continues listening for next request

## Example 3: Complex design request

**Figma plugin message:** "build a dashboard that uses the THEME.js design style"

**Assistant:**
1. Receives message
2. Reads THEME.js for complete styling reference
3. Creates dashboard with:
   - Dark sidebar (#13120F from catalog.dark.background)
   - Metric cards with gradient colors
   - Plantin MT Pro for headings
   - Apertura for body text
   - Proper spacing tokens (24px, 32px)
4. Continues listening

## Example 4: Session continuation

If servers are already running from previous session:

**User:** `/design-figma-sketch`

**Assistant:**
1. Detects servers already running
2. Asks for channel ID
3. Joins channel
4. Starts listening immediately

## Design Token Usage Examples

### Colors
- Primary actions: `#3600aa` (Bumba blue)
- Success states: `#00AA00` (gradient green)
- Warnings: `#FFAA00` (gradient orange-yellow)
- Errors: `#DD0000` (gradient red)
- Dark backgrounds: `#13120F` (catalog dark)

### Typography
- Headings: Plantin MT Pro
- Body text: Apertura
- Captions/Code: iA Writer Mono S

### Spacing
- Component padding: 24px
- Large gaps: 32px
- Border radius: 8px (sm), 12px (lg)

### Components
- Button padding: `16px 40px` (md)
- Input padding: `12px 16px`
- Card padding: `24px`
