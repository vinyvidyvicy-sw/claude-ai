# Pemetaan dokumen ke kartu Metrodata AI Use Case

Sumber: `Metrodata_AI_Use_Case.pdf` (13 halaman). Halaman 1 hanya judul "Detail Use Cases" dan halaman 13 hanya "Thank You!"; keduanya tidak memuat penjelasan use case.

Aturan: teks di bawah disalin **apa adanya** dari dokumen (bahasa Inggris), tidak diringkas, tidak diterjemahkan, tidak ditambah.

Dikecualikan atas permintaan:
- "Agentic procurement document processing" (halaman 2, 11, 12) tidak dimasukkan ke kartu mana pun. Kartu "Document Procurement" tidak berisi teks dari dokumen.
- Kartu "Joint Planning Session" dan "Go To Market" dilewati (tidak dipetakan).

Catatan: kartu "Real-time Component Inspection" dipetakan ke "Real time car component inspection" (halaman 2) / "Manufacturing, real time component inspection" (halaman 9). Kata "car" hanya muncul di halaman 2.

---

**Metrodata Use Case Card:** Trade Finance Document Examination

**Document Explanations (As-Is):**

- *Title in the document:* Trade finance document examination
- *Page 2 (overview table):*
  - One-line description: Reads every page of a trade document set, checks it against the credit terms and the bank's rules, and explains each finding.
  - Industry: Banking, 2026
  - Runs on: Dataiku and Amazon Bedrock, hybrid
  - Timeline: 2 months, one use case
  - Level: Level 2
- *Page 3: Banking, trade finance document examination*
  - Subtitle: Dataiku on the bank's servers with Amazon Bedrock in AWS Jakarta, a 2 month project, in the seven blueprint sections
  - 1. Problem statement and owner
    - Owner: Trade operations, with the checkers
    - Every document set examined by hand, page by page
    - Fields compared across documents and the credit terms
    - Each discrepancy written up with its page and article
    - Parties and prices checked one by one
  - 2. High level solution
    - One examination run for every new document set
    - Each page is read once, the fields are examined against the credit terms and the bank's rules, and every finding is explained. Checkers accept, overrule and sign.
    - WHAT IT DOES
    - Reads every page, its document and fields
    - Examines the set against the bank's rules
    - Explains each finding and drafts the notice
  - 3. Level of trust and human gates
    - Level 2 - Prepares, you decide
    - The checker accepts or overrules each finding
    - Trade compliance reviews flagged parties
    - Trade operations honours or sends the refusal
  - 4. Data and system readiness
    - Sample document sets with past findings
    - The bank's matching rules and SOPs
    - Three Linux VMs on the bank's servers
    - Private network from the bank to AWS Jakarta
  - High level solution, architecture
    - Document sets land in the to check folder: Document set PDF; Credit terms and rules
    - Dataiku Automation node on the bank's servers: Render every page; Check every field
    - AI reads, examines and explains: Amazon Bedrock Jakarta; Findings and notice
    - Automation screens and sorts the result: Parties and prices; Clean or corrections
    - Checker decision and the process log: Accept, overrule, sign; Write once log
  - 5. Expected business impact
    - Target of two minutes or less per set
    - Every finding shown with its page and reason
    - Checkers review findings, not every page
  - 6. Effort, duration and team
    - 2 months
    - one use case, network and AI teams
  - 7. Sequence and roadmap
    - Phase 1, discovery, FSD and design approval
    - Phase 2, AWS network, Dataiku and the build
    - Phase 3, SIT, UAT and handover
- *Page 4: Banking, the document examination flow*
  - Subtitle: The high level solution as lanes, from a new document set to the checker's signature and the process log
  - Stages
    - 01 Receive
    - 02 Read
    - 03 Verify
    - 04 Examine
    - 05 Decide
    - 06 Close
  - PEOPLE (Trade ops, checker, compliance)
    - (1) Trade operations drops the document set in, or the trade system sends it
    - (6) Trade compliance reviews any party or price that was flagged
    - (9) The checker opens it, accepts or overrules each finding, and signs
    - (10) Trade operations honours or sends the refusal
  - AI (Reads, examines, explains)
    - (3) The AI reads each page once: the document it belongs to, and every field
    - (7) The AI examines the documents against the rules, explains each finding and drafts the notice
  - AUTOMATION (Folders, checks, the record)
    - (2) A new file starts the run, and every page is rendered as an image
    - (4) Pages are grouped into documents, and each field is checked against its page
    - (5) Parties are screened and prices checked against the market
    - (8) The document set lands in out / clean, or in out / corrections
    - (11) Every decision, override and source is written to the process log

**Location in PDF:** pages 2, 3, 4 (page 2 overview; the other pages are the seven blueprint sections and the flow)

---

**Metrodata Use Case Card:** Customer Analytics and Credit Scoring

**Document Explanations (As-Is):**

- *Title in the document:* Customer analytics and credit scoring
- *Page 2 (overview table):*
  - One-line description: Five models on one platform: customer segments, churn risk, offers for civil servants, customer profitability and credit scores.
  - Industry: Banking, 2026
  - Runs on: Dataiku, hybrid
  - Timeline: 7 months, five models
  - Level: Level 2
- *Page 5: Banking, customer analytics and credit scoring*
  - Subtitle: Five models on Dataiku in a hybrid setup, a 7 month project that started in September 2026, in the seven blueprint sections
  - 1. Problem statement and owner
    - Owner: Business and credit units, with IT
    - Which customers belong together, and why
    - Which customers will go dormant or close their account
    - Which product to offer each civil servant
    - Fee and interest income and credit risk per customer
  - 2. High level solution
    - Five models on one Dataiku platform
    - Customer and transaction history feed five models that segment customers, flag churn, suggest offers, estimate profitability and score credit. Teams act on the scores.
    - WHAT IT DOES
    - Segment and churn risk per customer
    - Next offer and profitability per customer
    - Credit score per civil servant debtor
  - 3. Level of trust and human gates
    - Level 2 - Prepares, you decide
    - Business teams decide who gets which offer
    - Credit officers decide every application
    - Risk and IT approve each model release
  - 4. Data and system readiness
    - Customer and account data in one place
    - Transaction history for every customer
    - Loan and repayment history for scoring
    - Dataiku in a hybrid setup
  - High level solution, architecture
    - Customer, account and transaction data: Core banking data; Loan history
    - Data preparation in Dataiku: Clean and join; Features per customer
    - AI models score every customer: Segment and churn; Offer, profit, credit
    - Automation refreshes data and scores: Scheduled runs; Scores to the teams
    - Decisions and model monitoring: Offers and loans; Model performance
  - 5. Expected business impact
    - Offers matched to each customer segment
    - Churn risk seen before an account closes
    - Credit decisions backed by one score
  - 6. Effort, duration and team
    - 7 months
    - five models, started September 2026
  - 7. Sequence and roadmap
    - Phase 1, customer data prepared in Dataiku
    - Phase 2, the five models built and tested
    - Phase 3, scores in use and monitored
- *Page 6: Banking, the customer analytics flow*
  - Subtitle: The high level solution as lanes, from customer data to the scores that business and credit teams act on
  - Stages
    - 01 Collect
    - 02 Prepare
    - 03 Segment
    - 04 Offer
    - 05 Credit
    - 06 Monitor
  - PEOPLE (Business, credit and risk teams)
    - (4) Business teams review the segments and the churn list
    - (6) Business teams choose which offers go to whom
    - (8) Credit officers decide each application with the score
    - (10) Risk and IT review model performance and approve changes
  - AI (Segments, predicts, scores)
    - (3) Customers grouped into segments and scored for churn risk
    - (5) Next offer and profitability estimated for each customer
    - (7) Credit score calculated for each civil servant debtor
  - AUTOMATION (Loads, prepares, refreshes)
    - (1) Customer, account and transaction data loaded into Dataiku
    - (2) Data cleaned, joined and turned into features per customer
    - (9) Scheduled runs refresh the data and the scores

**Location in PDF:** pages 2, 5, 6 (page 2 overview; the other pages are the seven blueprint sections and the flow)

---

**Metrodata Use Case Card:** Predictive Maintenance for Machines

**Document Explanations (As-Is):**

- *Title in the document:* Predictive maintenance for machines
- *Page 2 (overview table):*
  - One-line description: Predicts which machine is likely to fail from its machine data, so maintenance can act before a breakdown stops the line.
  - Industry: Manufacturing, 2024
  - Runs on: Amazon SageMaker, cloud
  - Timeline: 5 months, one use case
  - Level: Level 2
- *Page 7: Manufacturing, predictive maintenance for machines*
  - Subtitle: Amazon SageMaker in the cloud, a 5 month project from November 2024, in the seven blueprint sections
  - 1. Problem statement and owner
    - Owner: Maintenance, with production
    - Machines that fail without warning and stop the line
    - Service done by the calendar, not by condition
    - Spare parts and crews arranged after the stop
    - Little time to plan a repair before a failure
  - 2. High level solution
    - Failure prediction from machine data
    - Machine data feeds a model on Amazon SageMaker that predicts which machine is likely to fail, so maintenance can plan the repair before the line stops.
    - WHAT IT DOES
    - Collects and prepares the machine data
    - Predicts the risk of failure per machine
    - Warns maintenance before a breakdown
  - 3. Level of trust and human gates
    - Level 2 - Prepares, you decide
    - Maintenance decides every repair
    - Production agrees any planned stop
    - Engineers review the model before changes
  - 4. Data and system readiness
    - Machine sensor readings over time
    - Failure and repair history per machine
    - A cloud data store on AWS
    - A secure link from the plant to AWS
  - High level solution, architecture
    - Machine data from the line: Sensor readings; Repair history
    - Secure link from the plant to AWS: Data upload; Cloud storage
    - AI predicts the risk of failure: Trained on SageMaker; Scores new data
    - Automation sends the warning: Risk per machine; Alert to maintenance
    - Repair decision and the record: Planned repair; Model monitoring
  - 5. Expected business impact
    - Repairs planned before a breakdown
    - Fewer unplanned stops on the line
    - Spare parts and crews ready in time
  - 6. Effort, duration and team
    - 5 months
    - one use case, from November 2024
  - 7. Sequence and roadmap
    - Phase 1, machine data connected and prepared
    - Phase 2, failure model trained and tested
    - Phase 3, warnings to maintenance, then monitoring
- *Page 8: Manufacturing, the predictive maintenance flow*
  - Subtitle: The high level solution as lanes, from machine data to a planned repair before the line stops
  - Stages
    - 01 Collect
    - 02 Learn
    - 03 Predict
    - 04 Plan and repair
    - 05 Record
  - PEOPLE (Maintenance and production)
    - (6) Maintenance plans the repair, parts and crew with production
  - AI (Learns, predicts)
    - (3) Failure model trained on the prepared history
    - (4) New readings scored for the risk of failure
    - (8) The model retrained as new failures are recorded
  - AUTOMATION (Collects, warns, records)
    - (1) Sensor readings from each machine sent to the cloud
    - (2) Readings cleaned and joined with the repair history
    - (5) A warning sent when a machine's risk is high
    - (7) Each repair recorded and added to the history

**Location in PDF:** pages 2, 7, 8 (page 2 overview; the other pages are the seven blueprint sections and the flow)

---

**Metrodata Use Case Card:** Real-time Component Inspection

**Document Explanations (As-Is):**

- *Title in the document:* Real time car component inspection (page 2); Manufacturing, real time component inspection (page 9)
- *Page 2 (overview table):*
  - One-line description: Checks every component image from the line camera in real time and flags the parts that need attention.
  - Industry: Manufacturing, 2023
  - Runs on: Amazon SageMaker, cloud
  - Timeline: 4 months, with predictive maintenance on two lines
  - Level: Level 2
- *Page 9: Manufacturing, real time component inspection*
  - Subtitle: Amazon SageMaker in the cloud, a 4 month project from December 2023 that also covered predictive maintenance on two lines
  - 1. Problem statement and owner
    - Owner: Quality, with production
    - Components checked by eye on a moving line
    - Defects found late, after the next station
    - Results that differ between inspectors
    - No image record of what was checked
  - 2. High level solution
    - Camera inspection with object detection
    - A camera captures each component and an object detection model on Amazon SageMaker checks every image in real time. Operators act on the flagged parts.
    - WHAT IT DOES
    - Captures every component on camera
    - Detects defects in each image in real time
    - Flags the parts that need attention
  - 3. Level of trust and human gates
    - Level 2 - Prepares, you decide
    - Operators confirm every flagged part
    - Quality decides on rework or scrap
    - Engineers review the model before changes
  - 4. Data and system readiness
    - A camera at each inspection point
    - Labelled images of good and defective parts
    - Clear pass and fail criteria
    - A secure link from the line to AWS
  - High level solution, architecture
    - Camera at the inspection point: Image per component; Line and station
    - Secure link from the line to AWS: Image upload; Cloud storage
    - AI detects defects in real time: Trained on SageMaker; Checks each image
    - Automation marks the result: Passed or flagged; Alert to the operator
    - Operator decision and the record: Rework or scrap; Image record
  - 5. Expected business impact
    - Every component checked the same way
    - Defects caught at the inspection point
    - An image record for every component
  - 6. Effort, duration and team
    - 4 months
    - two use cases, from December 2023
  - 7. Sequence and roadmap
    - Phase 1, images collected and labelled
    - Phase 2, detection model trained and tested
    - Phase 3, real time inspection on the line
- *Page 10: Manufacturing, the inspection flow*
  - Subtitle: The high level solution as lanes, from the camera image to the decision on each flagged part
  - Stages
    - 01 Prepare
    - 02 Capture
    - 03 Detect
    - 04 Confirm
    - 05 Close
  - PEOPLE (Operators and quality)
    - (1) Quality labels sample images of good and defective parts
    - (6) The operator checks each flagged part on the line
    - (7) Quality decides on rework or scrap
  - AI (Learns, detects)
    - (2) A detection model is trained on the labelled images
    - (4) Each image is checked for defects in real time
  - AUTOMATION (Captures, marks, records)
    - (3) The line camera captures each component at the station
    - (5) The component is marked as passed or flagged
    - (8) The result and the image are stored for every component

**Location in PDF:** pages 2, 9, 10 (page 2 overview; the other pages are the seven blueprint sections and the flow)
