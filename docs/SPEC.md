# Build a Personal AI-Powered University Revision Platform

I want you to act as the **lead software architect, senior full-stack developer, AI engineer, database designer, UX designer and testing engineer** for this project.

I want you to build a serious, production-quality personal university revision platform for me.

This is **not intended to be a basic student website**. I want it to feel like a polished SaaS/productivity application, combining the functionality of a revision platform, AI tutor, adaptive learning system, document knowledge base, revision planner and academic dashboard.

I am a student studying **BSc Mathematics with Finance at the University of Liverpool**.

You already have context about my current modules, but the application must allow me to add, edit and remove modules as I progress through university.

---

# 1. VERY IMPORTANT: BUILD THIS ITERATIVELY

Do NOT attempt to create the entire application in one enormous response.

First:

1. Analyse the requirements.
2. Identify any contradictions or missing technical requirements.
3. Design the overall architecture.
4. Recommend the technology stack.
5. Design the database schema.
6. Design the AI/RAG architecture.
7. Design the frontend structure.
8. Design the API/backend structure.
9. Design the file-processing pipeline.
10. Design authentication and security.
11. Create an implementation roadmap.

Then build the application **stage by stage**.

After each major stage:

- Run tests.
- Check for errors.
- Review the architecture.
- Fix problems.
- Make sure the existing functionality still works.
- Only then proceed to the next stage.

Do not sacrifice architecture or security simply to get something working quickly.

---

# 2. CORE GOAL

The website should become my central university revision environment.

I should be able to:

- Upload university materials.
- Organise them by module/topic.
- Have Claude understand those materials.
- Search through them.
- Ask questions about them.
- Generate revision materials.
- Generate questions.
- Generate quizzes.
- Generate flashcards.
- Generate mock exams.
- Track my performance.
- Identify weaknesses.
- Track mistakes.
- Build revision schedules.
- Automatically adapt revision based on performance.
- Track exams.
- Receive reminders.
- Practise coding.
- Have Claude act as an AI tutor.
- Store everything permanently.
- Search across my entire academic knowledge base.

The system should continuously learn from my performance and use that information to improve future revision.

---

# 3. DESIGN PHILOSOPHY

The application should feel like a combination of:

- Notion
- Anki
- a modern university learning platform
- an AI tutor
- a productivity dashboard
- a personal knowledge base
- an adaptive exam-preparation platform

The design should be:

- Clean
- Minimal
- Modern
- Professional
- Polished
- Fast
- Responsive
- Intuitive
- Serious rather than childish

Use a modern SaaS-style interface while maintaining the simplicity and organisation of Notion.

It should work properly on:

- Desktop
- Laptop
- Tablet
- Mobile

Support:

- Light mode
- Dark mode
- System theme
- Customisable accent colour

---

# 4. HOMEPAGE / MAIN DASHBOARD

When I open the application, I want a dashboard similar to:

> Good afternoon, Ewan
>
> **Today's Progress**
> 67%
>
> 🔥 8-day streak
>
> ### Today's Revision
> Calculus — 45 min
> Finance — 30 min
> Statistics — 30 min
>
> ### Daily Quiz
> 15 questions
>
> ### Weak Topics
> Integration by Parts — 43%
> Probability Distributions — 51%
>
> ### Upcoming Exams
> Calculus — 34 days

The exact information should dynamically change based on my data.

The dashboard should show:

- Today's revision
- Daily quiz
- Current streak
- Questions attempted
- Accuracy
- Recent performance
- Weak topics
- Strong topics
- Upcoming exams
- Revision schedule
- Recently uploaded materials
- Recently generated materials
- Recommended next activity
- Study time
- Module progress
- Flashcard reviews
- Mistake-bank items
- Notifications

Claude should be able to determine what is most useful to display.

---

# 5. MODULE SYSTEM

I want a module-based structure.

Example:

University
→ Academic Year
→ Module
→ Topic
→ Subtopic
→ Materials

For example:

Mathematics
→ Calculus
→ Integration
→ Integration by Parts

or:

Finance
→ Financial Mathematics
→ Interest Rates
→ Continuous Compounding

The exact current modules are already known to you, but DO NOT hard-code them into the application.

I need to be able to:

- Add modules
- Rename modules
- Archive modules
- Delete modules
- Add topics
- Add subtopics
- Edit topics
- Reorganise topics

Claude should also be able to suggest topics based on uploaded lecture materials.

---

# 6. ACADEMIC YEARS

The system must support multiple academic years.

For example:

2026/27 — Year 1

2027/28 — Year 2

2028/29 — Year 3

My data from previous years must remain accessible.

I should be able to switch between academic years.

My historical:

- questions
- scores
- notes
- flashcards
- materials
- revision plans
- exams
- study time

should not disappear when I move into another year.

---

# 7. MODULE DASHBOARD

Every module should have its own dashboard.

Each module should contain sections such as:

- Overview
- Notes
- University Materials
- My Revision Materials
- Claude Generated Materials
- Questions
- Question Bank
- Flashcards
- Mock Exams
- Mistake Bank
- Progress
- Topics
- Revision Plan
- Ask Claude

For example:

## Calculus

**Progress: 72%**

Topics:

- Differentiation — 91%
- Integration — 72%
- Integration by Parts — 43%
- Series — 61%

Recent activity:

- 20 questions completed
- 16 correct
- 80% accuracy
- 35 minutes studied

Claude recommendation:

> Focus on Integration by Parts today. Your recent accuracy is 43% and you have not reviewed it for 6 days.

---

# 8. FILE UPLOAD SYSTEM

I want to upload university materials directly to the website.

I do NOT need Google Drive integration.

The application should support common academic file types including:

- PDF
- DOCX
- PPTX
- XLSX
- CSV
- TXT
- Markdown
- Images
- Photos of handwritten notes
- Other useful academic formats where practical

The application should allow files to be stored either:

- Locally during development / where appropriate
- Or through secure cloud/object storage

Choose the architecture that makes the most sense.

The storage system must be abstracted so that changing storage providers later is not unnecessarily difficult.

---

# 9. FILE ORGANISATION

When uploading a file, I should be able to associate it with:

- Academic year
- Module
- Topic
- Subtopic
- Material type
- Lecture/week if appropriate
- My own material vs university material

Example:

> Calculus
> → Integration
> → Week 5
> → Lecture 5.pdf

I should also be able to upload a file and let Claude analyse it and suggest where it belongs.

---

# 10. CLAUDE MUST ACTUALLY UNDERSTAND THE FILES

This is extremely important.

Do NOT simply store PDFs and display their filenames.

Claude needs to be able to actually understand the contents.

Implement a proper document-processing/RAG architecture.

The intended process is approximately:

Upload file

↓

Extract text/content

↓

OCR images/handwritten material where possible

↓

Split content into appropriate chunks

↓

Generate embeddings

↓

Store searchable representations

↓

Associate chunks with:

- module
- topic
- subtopic
- document
- page/slide where possible

↓

Retrieve relevant material when Claude needs it

↓

Provide relevant context to Claude

The system should NOT send an entire 300-page PDF to Claude every time I ask one question.

Use retrieval so Claude receives the most relevant material.

---

# 11. MULTIMODAL MATERIALS

The system should handle:

- Text PDFs
- Scanned PDFs
- Photos
- Diagrams
- Tables
- Handwritten notes
- Mathematical notation
- PowerPoint slides
- Word documents
- Spreadsheets

Where practical, preserve page/slide/image references.

For mathematics, take particular care with:

- equations
- symbols
- matrices
- formulas
- graphs
- notation

Do not destroy mathematical meaning during extraction.

---

# 12. SOURCE PRIORITY

Claude should be able to use three levels of knowledge:

### Priority 1
My uploaded university material.

### Priority 2
My own revision materials and previous generated materials.

### Priority 3
Claude's general academic knowledge.

However, Claude should be able to use **all three**, not only the university material.

When answering an academic question, Claude should prefer my university material when relevant.

If there is a conflict between sources, Claude should explicitly explain it.

For example:

> Your lecture notes define X as...
>
> Another source describes X as...
>
> The difference appears to be...

Claude must not silently choose one source when there is a meaningful contradiction.

---

# 13. SOURCE CITATIONS

When Claude answers questions using my uploaded materials, it should provide citations where possible.

For example:

> According to Week 4 Lecture Notes, integration by parts is introduced using...

**Source: Calculus Week 4 Lecture.pdf — Page 17**

Clicking the citation should ideally open the relevant document/page.

If the answer uses multiple sources, show each relevant source.

The system should distinguish between:

- University source
- My own notes
- Claude-generated material
- General Claude knowledge

---

# 14. GLOBAL SEARCH

Create a powerful global search.

It should search across:

- Modules
- Topics
- Subtopics
- Uploaded files
- Contents of uploaded files
- My revision materials
- Claude-generated materials
- Questions
- Flashcards
- Mock exams
- Mistakes
- Definitions
- Formulas

This must be **content-aware search**, not just filename search.

For example, searching:

> Black-Scholes assumptions

could return a relevant paragraph from a lecture PDF even if the words aren't in the filename.

---

# 15. CLAUDE AI INTEGRATION

Claude should be the core AI engine of the application.

Use the **Anthropic Claude API** directly.

The architecture should be:

Website

↓

Backend

↓

AI orchestration layer

↓

Claude API

The API key must NEVER be exposed to the frontend.

Use secure environment variables/secrets.

Never hard-code:

- API keys
- passwords
- database credentials
- private tokens

---

# 16. CLAUDE SHOULD BE ABLE TO TAKE ACTIONS

Claude should not just be a chat window.

It should be able to interact with the application's functionality through properly designed backend tools/function calls.

For example, I could tell Claude:

> Create a revision guide for Week 4 Calculus.

Claude should be able to:

1. Find Week 4 materials.
2. Retrieve relevant content.
3. Generate the guide.
4. Show me a preview.
5. Save it to the appropriate module.

Similarly:

> I have 45 minutes. What should I revise?

Claude should analyse:

- upcoming exams
- weak topics
- previous performance
- revision history
- spaced repetition requirements
- unfinished revision
- available materials

and produce an appropriate session.

---

# 17. CLAUDE ACTION PERMISSIONS

Claude should generally be allowed to perform non-destructive actions automatically.

It can:

- Create materials
- Update materials
- Create questions
- Create flashcards
- Create revision plans
- Organise files
- Create topics
- Analyse performance
- Update recommendations
- Update the learning profile

However:

## DELETE ACTIONS REQUIRE CONFIRMATION

Claude must ask for explicit confirmation before deleting:

- Files
- Revision materials
- Questions
- Flashcards
- Modules
- Topics
- Revision plans
- Important data

Example:

> Are you sure you want me to delete "Calculus Week 4 Revision Guide"?

Do not allow destructive actions to happen silently.

---

# 18. GENERATED MATERIALS

Claude should be able to generate:

- Flashcards
- Practice questions
- Exam questions
- Revision guides
- Topic summaries
- Concept maps
- Coding exercises
- Mock exams
- Worked examples
- Formula sheets
- Definitions
- Topic explanations

Generated materials should be saved permanently.

Do not make generated content disappear when the chat ends.

---

# 19. GENERATED VS MY MATERIALS

Keep my materials separate from Claude's.

For example:

### My Revision Materials

Things I created/uploaded.

### Claude Generated

Things Claude generated.

Both should be permanently stored.

Claude can analyse my own material and suggest improvements.

If Claude improves one of my materials, **never overwrite the original automatically**.

Create a new version instead.

---

# 20. VERSION HISTORY

Important generated/revision materials should support version history.

For example:

Revision Guide v1

Revision Guide v2

Revision Guide v3

I should be able to:

- View previous versions
- Compare versions where practical
- Restore a previous version

Deleting a version requires confirmation.

---

# 21. DAILY QUIZ

Create a Daily Quiz system.

Initially, questions should be distributed relatively evenly across my modules/topics.

However, the quiz must become adaptive.

Over time it should consider:

- Accuracy
- Difficulty
- Recency
- Time since last review
- Number of attempts
- Mistakes
- Weak topics
- Strong topics
- Exam dates
- Spaced repetition
- Question difficulty

Weak topics should receive more attention.

Strong topics should receive less repetitive attention.

The system should decide the appropriate number of daily questions based on my workload and learning needs.

Do not hard-code a fixed number if an adaptive approach would be better.

The system should remember my performance over time.

---

# 22. SPACED REPETITION

Use spaced repetition principles.

Questions/flashcards should return at appropriate intervals.

Incorrect or poorly remembered material should return sooner.

Strongly remembered material should return later.

Combine this with:

- Exam proximity
- Topic importance
- Recent mistakes
- Confidence
- Difficulty

The goal is long-term retention rather than simply maximising today's score.

---

# 23. QUESTION TYPES

Claude should decide the most appropriate question format for the topic.

Possible formats include:

- Multiple choice
- Short answer
- Numerical calculations
- Mathematical derivations
- Explain a concept
- True/false
- Coding questions
- Worked problems
- Exam-style questions
- Multi-step problems

Do not use the same question format constantly.

---

# 24. QUESTION DIFFICULTY

Use difficulty levels such as:

- Easy
- Medium
- Hard
- Exam-level

Claude should dynamically adjust difficulty based on my performance.

If I consistently answer easy questions correctly, increase difficulty.

If I repeatedly fail difficult questions, provide intermediate practice and explanations.

---

# 25. QUIZ MARKING

I want to submit the entire quiz before receiving the results.

After submission:

Show:

- Score
- Accuracy
- Questions correct
- Questions incorrect
- Difficulty breakdown
- Topic breakdown
- Time taken
- Weak areas
- Recommended next steps

For every incorrect answer, Claude should explain:

1. Why my answer was wrong.
2. What the correct answer is.
3. The reasoning.
4. What mistake I made if identifiable.
5. How to avoid making it again.

---

# 26. QUESTION BANK

Each module should have a question bank.

Filters should include:

- Topic
- Subtopic
- Difficulty
- Question type
- Correct/incorrect
- Attempted/unattempted
- Exam relevance
- Date last attempted
- Confidence
- Source

Actions:

- Practice
- Generate more
- Retry wrong questions
- Practice weak topics
- Practice unattempted questions
- Build custom quiz
- Build mock exam

Questions should be generated from the relevant university material wherever possible.

---

# 27. MISTAKE BANK

Create a dedicated Mistake Bank.

Claude should identify recurring mistakes.

For example:

> Integration by Parts
>
> ❌ Incorrect choice of u  
> ❌ Forgot boundary evaluation  
> ❌ Algebraic simplification error

Claude should identify recurring patterns rather than simply recording that a question was wrong.

Future questions should deliberately test recurring weaknesses.

---

# 28. PERSONAL LEARNING PROFILE

Create a long-term learning profile.

Claude should gradually understand patterns such as:

- Strong conceptual understanding
- Weak multi-step calculations
- Frequent algebra mistakes
- Strong statistics
- Weak probability
- Good recall
- Poor application under exam conditions

This information should influence:

- Daily quizzes
- Questions
- Revision plans
- Flashcards
- Mock exams
- Recommendations

Do not make unsupported psychological claims.

The learning profile should be based on observable performance data.

---

# 29. FLASHCARDS

Create an Anki-style flashcard system.

Example:

**Front**

> What is the Central Limit Theorem?

↓

**Reveal Answer**

↓

How well did you know it?

- Again
- Hard
- Good
- Easy

Use these responses for spaced repetition.

Flashcards should support:

- Text
- Mathematical notation
- Images
- Formulas
- Definitions
- Examples
- Source citations

Claude should be able to generate flashcards from university materials.

---

# 30. AUTOMATIC MATERIAL ANALYSIS

When I upload a new lecture/material, Claude should be able to analyse it.

It should identify:

- Topics
- Subtopics
- Definitions
- Formulas
- Important concepts
- Examples
- Potential exam material
- Relationships to existing topics
- Prerequisite knowledge
- Potential gaps

It should also be able to automatically suggest:

- Flashcards
- Questions
- Revision guide
- Summary
- Topic map

I should be able to choose what gets generated.

---

# 31. MY OWN MATERIALS

If I upload my own revision guide, Claude should be able to:

- Analyse it
- Find errors
- Identify missing concepts
- Compare it against university material
- Suggest improvements
- Generate additional questions
- Improve explanations

However, my original material must remain untouched.

Claude should create an improved version rather than silently replacing my original.

---

# 32. REVISION PLANNER

Create an intelligent revision planner.

I should be able to enter:

- Exams
- Exam dates
- Exam times
- Exam duration
- Exam location
- Module
- Exam weighting
- Topics covered
- Personal confidence

Claude should use this information when creating my revision plan.

---

# 33. ADAPTIVE REVISION SCHEDULE

The revision schedule should consider:

- Exam dates
- Module importance
- Topic difficulty
- Current performance
- Weak topics
- Strong topics
- Time since revision
- Available study time
- Uncompleted work
- Flashcard reviews
- Daily quizzes
- Mistake Bank
- Previous study time

The schedule should automatically adapt.

If I improve significantly in a topic, reduce its priority.

If I struggle with a topic, increase its priority.

If an exam approaches, adjust priorities accordingly.

---

# 34. AVAILABLE STUDY TIME

I should be able to tell Claude:

> I have 2 hours today.

or:

> I have 3 hours every weekday but only 1 hour at weekends.

Claude should build the schedule around this.

The system should avoid creating unrealistic workloads.

---

# 35. REVISION CALENDAR

Create a proper calendar.

Views:

- Today
- Day
- Week
- Month

Show:

- Revision sessions
- Exams
- Completed sessions
- Missed sessions
- Quizzes
- Flashcard reviews
- Deadlines
- Important academic events

Allow me to manually adjust sessions.

Claude can then rebalance the future schedule.

---

# 36. EXAM MODE

Create a dedicated Exam Mode.

Features:

- Timed exam
- Countdown
- No AI assistance
- No hints
- Questions presented appropriately
- Optional sequential question mode
- Final submission
- Automatic marking where possible
- Detailed performance report

After completion:

Claude should analyse:

- Score
- Topics
- Time management
- Mistakes
- Difficulty
- Weak areas
- Recurring errors

Then update the revision recommendations.

---

# 37. CODING PRACTICE

Because my degree and career interests involve programming, create a coding-practice component.

Claude should be able to generate coding exercises.

For example:

```python
import pandas as pd

# Calculate rolling volatility...
```

Ideally provide an in-browser coding environment where technically practical.

The user should be able to:

- Write code
- Run code
- See output
- Receive feedback
- Get test results
- Ask Claude for hints

Claude should behave like a tutor.

Do not immediately reveal the full solution unless appropriate.

---

# 38. AI TUTOR MODE

Claude should act like an actual tutor.

If I say:

> I don't understand this integration question.

Claude should not automatically dump the complete answer.

Instead it should guide me.

For example:

> What method do you think might apply here?

Then progressively provide hints.

I should be able to request:

- Hint
- Stronger hint
- Explanation
- Full solution

The goal is learning, not simply answering everything for me.

---

# 39. GLOBAL AI ASSISTANT

There should be a global Claude interface.

I should be able to ask things such as:

> I have 45 minutes. What should I revise?

> What are my weakest topics?

> Make me a 20-question test on everything I've learned in calculus.

> I keep getting integration by parts wrong. Help me.

> Create a revision guide for Week 4.

> What should I revise before my next exam?

> Find where my lecture notes discuss Black-Scholes assumptions.

Claude should be able to perform appropriate actions rather than merely replying conversationally.

---

# 40. AI PREVIEW BEFORE SAVING

For generated revision materials, show me a preview before saving where appropriate.

For example:

> Claude generated:
>
> **Integration by Parts — Revision Guide**
>
> [Preview]
>
> Save
> Edit
> Regenerate
> Cancel

Once saved, it becomes persistent.

For routine low-risk generated content such as daily quiz questions, automatic saving is acceptable.

---

# 41. PROGRESS TRACKING

Track:

- Questions attempted
- Questions correct
- Accuracy
- Topics mastered
- Weak topics
- Study time
- Daily streak
- Quiz scores
- Module progress
- Revision material completion
- Flashcard performance
- Mock exam performance
- Mistakes
- Time spent per module
- Time spent per topic

---

# 42. TOPIC STRENGTH

Every topic should have an estimated strength.

Example:

> Integration — 72%
>
> Differentiation — 91%
>
> Series — 43%

Do not present these percentages as absolute measures of knowledge.

They should be clearly treated as an estimate based on available performance data.

The algorithm behind the score should be transparent and sensible.

---

# 43. ANALYTICS

Create useful analytics dashboards.

Examples:

### Module performance

Calculus — 76%

Finance — 84%

Statistics — 62%

### Question accuracy over time

Graph showing improvement.

### Study time

Hours per week.

### Topic strengths

Visual representation of topic performance.

### Mistake trends

Most common error categories.

### Revision consistency

Study streaks and completed sessions.

### Exam readiness

A data-driven summary based on:

- Coverage
- Recent performance
- Mock exam performance
- Weak topics
- Revision recency

Do not represent this as a guaranteed prediction of exam results.

---

# 44. NOTIFICATIONS

Support notifications such as:

> You haven't completed today's quiz.

> Your Finance exam is in 14 days.

> You haven't reviewed Integration by Parts for 9 days.

> You have 12 flashcards due today.

Support browser notifications where technically practical.

Allow notifications to be configured.

---

# 45. AI USAGE / COST DASHBOARD

Because the application uses the Claude API, create an AI usage dashboard.

Track:

- API requests
- Tokens used
- Estimated cost
- Cost by feature
- Cost by module
- Cost over time
- Model used

Allow reasonable safeguards against unexpectedly high API usage.

For example:

- Daily token limits
- Warning thresholds
- Confirmation for very large operations

---

# 46. CLAUDE MODEL SELECTION

Claude should choose which model is appropriate for each task.

For example:

- Simple quiz generation → faster/cheaper model
- Flashcard generation → faster model
- Large document analysis → appropriate high-context model
- Complex mathematical explanation → more capable model
- Revision planning → more capable model

Do not hard-code model choices unnecessarily.

Make model configuration easy to change.

---

# 47. DATABASE

Design a proper relational database.

At minimum, consider entities for:

- User
- AcademicYear
- Module
- Topic
- Subtopic
- Document
- DocumentChunk
- Material
- MaterialVersion
- Question
- QuestionAttempt
- Quiz
- QuizAttempt
- Flashcard
- FlashcardReview
- Mistake
- StudySession
- RevisionPlan
- Exam
- Notification
- AIInteraction
- AIUsage
- LearningProfile

Design relationships carefully.

Use migrations.

Do not store everything as one giant JSON object.

---

# 48. AUTHENTICATION & PRIVACY

This is a personal application for me.

However, implement proper security.

Use:

- Secure authentication
- Password hashing if password authentication is used
- Secure sessions/tokens
- Environment variables
- Proper access control
- Input validation
- File validation
- Secure file handling
- Protection against common web vulnerabilities
- Rate limiting where appropriate

My uploaded university materials are private.

No other user should be able to access them.

---

# 49. FILE SECURITY

Uploaded files must be handled securely.

Validate:

- File type
- File size
- Filename
- Storage location

Do not trust file extensions alone.

Prevent:

- Path traversal
- Malicious uploads
- Unauthorised access
- Accidental public exposure

Never expose private storage URLs unnecessarily.

---

# 50. BACKUP / EXPORT

I should never feel trapped inside the application.

Provide data export functionality.

Where practical, allow export of:

- Notes
- Revision materials
- Flashcards
- Questions
- Progress
- Revision plans
- Study history
- Uploaded files

Use sensible formats such as:

- JSON
- CSV
- PDF
- Markdown
- ZIP

depending on the data.

---

# 51. LOCAL DEVELOPMENT

I should be able to run the application locally.

Provide:

- Clear setup instructions
- Environment variables
- Database setup
- Migration commands
- Seed data if useful
- Development commands
- Testing commands

Create an appropriate `.env.example`.

Never commit actual secrets.

---

# 52. GITHUB-READY

I want the project to be suitable for GitHub.

The code should be:

- Clean
- Modular
- Well documented
- Maintainable
- Secure
- Professionally structured

Include:

- README
- Architecture documentation
- Setup instructions
- Environment variable documentation
- Database documentation
- API documentation
- Testing instructions
- Deployment instructions
- `.gitignore`
- `.env.example`

Do not include:

- API keys
- passwords
- personal secrets
- private files
- database credentials

---

# 53. TECHNOLOGY STACK

Choose an appropriate modern stack based on the requirements.

I am comfortable with Python, SQL, HTML/CSS/JavaScript and general programming.

Prefer technologies that are:

- Reliable
- Well documented
- Maintainable
- Suitable for AI/RAG
- Good for mathematical applications
- Good for file processing
- Easy to run locally
- Suitable for future deployment

You are responsible for recommending the stack.

Explain why you selected each major technology.

Do not select technologies simply because they are trendy.

---

# 54. RAG ARCHITECTURE

I specifically want you to design a proper RAG system.

Consider:

- Document parsing
- OCR
- Chunking
- Metadata
- Embeddings
- Vector database
- Hybrid search
- Keyword search
- Semantic search
- Reranking where useful
- Context assembly
- Citation tracking
- Source attribution

The RAG system should allow Claude to retrieve relevant university material efficiently.

Make the architecture replaceable so the vector database can be changed later.

---

# 55. MATHEMATICAL CONTENT

Because this is a Mathematics with Finance degree, the system must handle mathematical content properly.

Support:

- LaTeX
- Equations
- Matrices
- Functions
- Integrals
- Derivatives
- Probability notation
- Statistics
- Financial mathematics
- Mathematical graphs

Use appropriate rendering such as KaTeX/MathJax where appropriate.

Do not render mathematical expressions as plain unformatted text when proper rendering is possible.

---

# 56. FINANCE CONTENT

The application should also support:

- Financial mathematics
- Statistics
- Probability
- Economics-related material
- Financial models
- Quantitative methods
- Programming for finance

Question generation should understand that finance questions may require:

- Numerical calculations
- Formula application
- Interpretation
- Explanation
- Multi-step reasoning

---

# 57. SEARCH + AI COMBINATION

The AI should be able to use the search system as a tool.

For example:

User:

> Where did my lecturer discuss the assumptions behind Black-Scholes?

Claude should:

1. Search the indexed university materials.
2. Find relevant passages.
3. Identify the source.
4. Return the answer.
5. Cite the relevant page/document.

This should not rely solely on Claude's internal knowledge.

---

# 58. USER CONTROL

Although Claude is deeply integrated, I should remain in control.

I should be able to:

- Edit generated materials
- Override revision schedules
- Change study availability
- Modify modules
- Modify topics
- Delete data with confirmation
- Change settings
- Regenerate content
- Disable notifications
- Export my data

Claude should assist rather than lock me into its decisions.

---

# 59. PERFORMANCE

The application should feel fast.

Do not block the entire UI while Claude processes a large document.

Use:

- Background jobs where appropriate
- Loading states
- Progress indicators
- Streaming responses where useful
- Caching where appropriate
- Async processing where appropriate

For example, after uploading a 200-page PDF:

> Upload complete  
> Processing document... 37%  
> Extracting content...  
> Indexing pages...

The user should be able to understand what is happening.

---

# 60. ERROR HANDLING

Build proper error handling.

If:

- Claude API fails
- File extraction fails
- OCR fails
- Embedding fails
- Database fails
- Network fails
- A file is unsupported

show a useful error.

Do not expose internal stack traces to the user.

Log errors appropriately for debugging.

---

# 61. TESTING

Testing is a major requirement.

Include:

- Unit tests
- Integration tests
- API tests
- Database tests
- RAG tests
- Authentication tests
- File upload tests
- AI tool/function tests
- Permission tests
- Frontend tests where appropriate

Especially test that:

- Users cannot access private files incorrectly.
- Claude cannot delete content without confirmation.
- Citations point to correct sources.
- Questions are correctly associated with topics.
- Progress is calculated correctly.
- Adaptive quizzes actually respond to performance.
- Revision plans update correctly.

---

# 62. AI EVALUATION

Create tests for AI-generated content.

For example, ensure generated questions:

- Are based on the correct material.
- Have valid answers.
- Match the intended difficulty.
- Are not duplicates unnecessarily.
- Don't contain hallucinated facts.
- Correctly reference sources where applicable.

Where possible, use deterministic validation rather than assuming Claude is always correct.

---

# 63. ACCESSIBILITY

Make the application accessible.

Consider:

- Keyboard navigation
- Semantic HTML
- Screen readers
- Good contrast
- Adjustable text
- Clear focus states
- Accessible buttons/forms
- Responsive layouts

---

# 64. UX DETAILS

Use polished interactions.

Examples:

- Command palette
- Global search
- Keyboard shortcuts
- Breadcrumbs
- Context menus
- Drag-and-drop file uploads
- Progress bars
- Charts
- Tooltips
- Loading skeletons
- Toast notifications
- Confirmation dialogs

Do not overdo animations.

The application should feel fast and professional.

---

# 65. SIDEBAR STRUCTURE

A sensible initial sidebar could be:

**Dashboard**

**My Modules**
- Mathematics
- Finance
- Statistics
- etc.

**Revision**
- Today's Revision
- Revision Plan
- Calendar

**Practice**
- Daily Quiz
- Question Bank
- Flashcards
- Mock Exams
- Mistake Bank

**Materials**
- University Materials
- My Materials
- Claude Generated

**Analytics**

**Ask Claude**

**Settings**

You may improve this structure if your UX analysis suggests something better.

---

# 66. SETTINGS

Create settings for:

- Profile
- Appearance
- Notifications
- AI preferences
- AI model preferences
- API usage limits
- Study availability
- Revision preferences
- Question difficulty
- Spaced repetition
- Data export
- Security

---

# 67. COMMAND PALETTE

Consider a command palette similar to modern productivity applications.

For example:

`Ctrl + K`

Then:

> Search...
>
> Ask Claude
> Create revision guide
> Generate quiz
> Upload material
> Start flashcards
> Start exam
> Open Calculus
> View weak topics

---

# 68. IMPORTANT AI PRINCIPLE

Do not let Claude hallucinate that it has accessed a source when it has not.

If no relevant university material is available, Claude should say so.

For example:

> I couldn't find this topic in your uploaded university materials. I can explain it using general knowledge, but this answer is not based on your lecture notes.

This distinction is important.

---

# 69. ACADEMIC INTEGRITY

The system is for my learning.

Claude should encourage understanding rather than simply doing all academic work for me.

For tutoring:

- Give hints
- Ask questions
- Encourage reasoning
- Explain mistakes
- Reveal solutions progressively

For practice questions, full solutions can be provided after an attempt.

---

# 70. DATA MODEL FOR PERFORMANCE

Performance should not simply be:

`correct / total`

Build a more meaningful system incorporating things such as:

- Accuracy
- Difficulty
- Recency
- Attempts
- Confidence
- Topic
- Subtopic
- Question type
- Time taken
- Spaced repetition state

The exact algorithm should be documented.

---

# 71. RECOMMENDATION ENGINE

Claude should be able to answer:

> What should I study next?

using actual data.

It should consider:

1. Upcoming exams.
2. Weak topics.
3. Recent mistakes.
4. Spaced repetition.
5. Uncovered material.
6. Recent study history.
7. Available time.
8. Topic importance.

Recommendations should be explainable.

For example:

> I recommend Integration by Parts because your recent accuracy is 43%, you have made 4 mistakes in this area, and you have not reviewed it for 6 days.

---

# 72. NO STATIC DEMO

Do not build a fake UI filled with static dummy data and consider the project complete.

The important functionality must actually work.

The application should have real:

- Database
- Authentication
- File uploads
- File processing
- RAG
- Claude API integration
- Question generation
- Progress tracking
- Revision planning
- Search
- Persistent storage

Use mock data only during development/testing where necessary.

---

# 73. DEVELOPMENT PROCESS

Build in stages.

A suggested order:

### Phase 1 — Architecture
- Finalise stack
- Database design
- Folder structure
- API architecture
- AI architecture

### Phase 2 — Foundation
- Project setup
- Authentication
- Database
- Basic UI
- Module system

### Phase 3 — File system
- Uploads
- Storage
- Parsing
- OCR
- Metadata
- Document management

### Phase 4 — Search/RAG
- Chunking
- Embeddings
- Vector database
- Search
- Citations

### Phase 5 — Claude
- Claude API
- AI orchestration
- Tool calling
- AI chat
- Source-aware answers

### Phase 6 — Revision materials
- Guides
- Flashcards
- Questions
- Mock exams

### Phase 7 — Adaptive learning
- Performance tracking
- Mistake Bank
- Learning profile
- Spaced repetition
- Adaptive quizzes

### Phase 8 — Revision planner
- Exams
- Calendar
- Study sessions
- Adaptive scheduling

### Phase 9 — Analytics
- Dashboard
- Progress
- Topic strength
- Study analytics

### Phase 10 — Coding practice
- Coding questions
- Execution environment if practical

### Phase 11 — Polish
- Responsive design
- Dark mode
- Accessibility
- Notifications
- Command palette

### Phase 12 — Security/testing
- Full test suite
- Security audit
- RAG evaluation
- AI evaluation
- Performance testing

### Phase 13 — Documentation/deployment
- README
- Setup guide
- Deployment
- Environment configuration
- Backup/export

---

# 74. HOW I WANT YOU TO WORK WITH ME

Do not assume that the first implementation is perfect.

After each major phase:

1. Explain what was built.
2. Show the important files/components.
3. Explain how they work.
4. Run/check tests.
5. Identify any issues.
6. Fix them.
7. Tell me what remains.
8. Continue to the next phase.

If you need to make an architectural decision, explain the trade-offs briefly and choose a sensible default.

Do not repeatedly ask me questions that are already answered in this specification.

Only ask me when a decision genuinely requires my input.

---

# 75. CODE QUALITY

Write professional code.

Use:

- Clear naming
- Modular architecture
- Separation of concerns
- Type safety where appropriate
- Reusable components
- Proper error handling
- Documentation
- Tests
- Sensible abstractions

Avoid:

- Giant files
- Giant functions
- Hard-coded values
- Duplicate logic
- Magic numbers
- Exposed secrets
- Temporary hacks becoming permanent architecture

---

# 76. FINAL PRODUCT

The finished application should effectively be my:

## Personal AI University Operating System

It should combine:

**Knowledge**

My university materials and notes.

**AI**

Claude as my tutor and academic assistant.

**Practice**

Questions, quizzes, flashcards and exams.

**Planning**

Adaptive revision schedules and exam preparation.

**Analytics**

Performance, mistakes and topic strengths.

**Search**

A searchable academic knowledge base.

**Programming**

Coding exercises and practice.

**Memory**

Persistent understanding of my materials and learning history.

---

# 77. FIRST TASK

Do NOT start writing the entire application yet.

Your first response should be the **Architecture & Technical Design Proposal**.

It should include:

1. Recommended technology stack
2. System architecture diagram
3. Frontend architecture
4. Backend architecture
5. Database schema
6. File storage architecture
7. RAG architecture
8. Claude API architecture
9. AI tool/function architecture
10. Adaptive learning architecture
11. Revision planner architecture
12. Authentication/security architecture
13. Testing strategy
14. Development folder structure
15. Development phases
16. Potential technical risks
17. Estimated complexity of each component
18. Any requirements you believe need clarification

Then wait for my approval before beginning Phase 1 implementation.

The goal is to build this as a **real, maintainable application**, not a quick prototype.