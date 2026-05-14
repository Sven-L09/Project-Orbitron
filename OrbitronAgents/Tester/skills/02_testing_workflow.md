# Testing Workflow

## Step-by-Step Testing Process

### 1. Understand Requirements
- Read the task description carefully
- Identify what the product is supposed to do
- Note specific requirements (responsive design, forms, navigation, etc.)

### 2. File Inspection
- Read every artifact file
- Check file sizes (empty or very small files are suspicious)
- Look for placeholder content (TODO, FIXME, Lorem ipsum, XXX)
- Check for debug code (console.log, debugger statements)

### 3. Quality Checks
Run each quality check tool:
- `check_html_structure` — Validate HTML files
- `check_code_quality` — Analyze code for issues
- `check_cross_file_consistency` — Verify files work together
- `check_requirements_coverage` — Compare against original requirements

### 4. Browser Testing (for HTML products)
- `browser_open_page` — Open the page in a real browser
- `browser_check_elements` — Verify key elements exist and are visible
- `browser_check_console` — Look for JavaScript errors
- `browser_test_responsive` — Check mobile/tablet/desktop views
- `browser_test_interaction` — Test buttons, forms, navigation
- `browser_get_page_info` — Get comprehensive page information

### 5. Report Results
Use `submit_test_result` with:
- Honest quality_rating (excellent/good/poor)
- Complete list of issues with severity
- Clear summary of findings
- Specific recommendations for improvement