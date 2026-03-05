You are a senior frontend engineer and product designer.

Create a fully working frontend-only prototype (HTML + CSS + Vanilla JavaScript, no frameworks) for a web app called:

"OralAI – Your AI Exam Professor"

The design must combine:
- The bold, dark, high-contrast hero style inspired by Redis.com
- The minimal, elegant, clean aesthetic inspired by Apple.com
- Modern AI SaaS landing page design
- Smooth typography and strong spacing hierarchy
- Professional product feel

The result must be:
- Clean
- Minimal
- Premium
- Not cluttered
- Ready to be connected later to a backend

Use:
- Pure HTML
- Pure CSS (no Tailwind, no Bootstrap)
- Vanilla JS
- Google Font: Inter or SF-like system font stack
- Responsive design

--------------------------------------------------
STRUCTURE
--------------------------------------------------

Create a single-page layout with the following sections:

1) NAVBAR (fixed top, glass/blur effect)
- Logo text: "OralAI"
- Links: How it Works | Features | Demo | Login
- CTA button: "Start a Simulation"
- Minimal Apple-style hover effects

2) HERO SECTION (Redis-inspired bold typography)
- Dark background (#0f172a or similar deep navy)
- Large bold headline (very large typography):
  "YOUR EXAM IS ABOUT TO GET EASIER"
- Subheadline:
  "Simulate real oral exams with AI feedback, scoring, and adaptive questions."
- Two buttons:
    - Primary: "Start Free Simulation"
    - Secondary: "See How It Works"
- Subtle gradient background glow
- Smooth fade-in animation on load

3) HOW IT WORKS SECTION (Apple minimal grid)
3 columns:
- 1. Choose Subject
- 2. Explain the Topic
- 3. Get Feedback & Score

Use minimal icon placeholders (simple circles or SVG shapes).
Very clean spacing, white background, lots of whitespace.

4) INTERACTIVE DEMO SECTION
Create a fake demo simulation UI:

Card-style container with:
- Dropdown: Level (High School / University)
- Input: Subject
- Textarea: "Explain your topic here..."
- Button: "Submit Simulation"

When clicking submit:
- Show a fake loading animation (2 seconds)
- Then display a mock AI evaluation panel with:
    - Score: 24/30
    - Strengths (bullet list)
    - Weaknesses (bullet list)
    - Follow-up questions (numbered list)

This must be done using simple JavaScript DOM manipulation.
No backend.

5) PROGRESS SECTION (Minimal stats style)
Simple horizontal cards:
- Exams Taken: 12
- Average Score: 25/30
- Improvement: +18%

Clean Apple-like cards with soft shadows.

6) FOOTER
Minimal
Dark background
Small centered text:
"© 2026 OralAI – AI-powered oral exam simulator"

--------------------------------------------------
DESIGN STYLE RULES
--------------------------------------------------

- Typography hierarchy must be strong.
- Hero headline must be VERY large and bold.
- Use generous spacing (min-height sections, padding: 100px+).
- Use subtle animations (fade-in, hover scale).
- Rounded corners (16px+).
- Soft shadows.
- Smooth transitions (0.3s ease).
- No clutter.
- No excessive colors.

Color palette:
Primary dark: #0f172a
Accent: soft red inspired by Redis (#dc2626 but softer)
Secondary accent: light blue glow
Background light sections: #f8fafc

Buttons:
- Primary: filled red
- Secondary: outline white (in hero)
- Smooth hover scaling

--------------------------------------------------
CODE REQUIREMENTS
--------------------------------------------------

- Everything must be in one HTML file.
- Separate <style> and <script> sections.
- Clean indentation.
- Comment main sections clearly.
- No external libraries except Google Fonts.
- Fully responsive down to mobile.
- No placeholders like lorem ipsum.
- Make it look like a real SaaS landing page.

--------------------------------------------------
GOAL
--------------------------------------------------

This is only a frontend prototype to visualize the product idea.
It should look like a real startup landing page, not a school project.
It must feel premium and modern.

Generate the complete working HTML file.