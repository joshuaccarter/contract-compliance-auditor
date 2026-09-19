# 📋 Vendor Contract Intake & Compliance Assessment

**Contract Title:** Apex Cloud Master Services Agreement  
**Vendor:** Apex Cloud Technologies, LLC  
**Overall Risk Assessment:** **CRITICAL**  

---

### Executive Compliance Scorecard

| Metric | Count | Percentage |
| :--- | :--- | :--- |
| **Total Checklist Items** | 10 | 100% |
| **Fully Compliant (MET)** | 2 | 20.0% |
| **Policy Deviations (DEVIATION)** | 5 | 50.0% |
| **Missing / Unaddressed (SILENT)** | 3 | 30.0% |

---

### Itemized Audit Review Matrix

| Item # | Focus Area | Policy Baseline Standard | Identified Vendor Term | Audit Verdict | Verbatim Citation / Section |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **REQ-01** | Service Level Agreement (SLA) | >= 99.9% availability commitment (commercially reasonable efforts acceptable) | Vendor commits to commercially reasonable efforts to maintain at least 99.9% System Availability per calendar month. | ✅ MET | Section 8.1: Vendor will use commercially reasonable efforts to ensure the SaaS Services maintain an operational System Availability of at least ninety-nine and nine-tenths percent (99.9%) during each calendar month, excluding scheduled maintenance. |
| **REQ-02** | SLA Service Credits | >= 10% monthly credit per 0.5% outage or escalating fee credit schedule | No financial remedy or service credit mechanism is provided for downtime or failure to meet availability targets. | ❌ SILENT | Not Found / Silent |
| **REQ-03** | Auto-Renewal Notice Window | >= 60 days prior notice (acceptable fallback: 45-60 days prior notice) | Non-renewal notice must be delivered at least 15 days prior to term expiration. | ⚠️ DEVIATION | Section 5.1: This Agreement shall automatically renew for additional successive twelve (12) month periods unless either party delivers written notice of non-renewal at least fifteen (15) days prior to the expiration of the current Term. |
| **REQ-04** | Termination for Convenience | Permitted with <= 30 days written notice (acceptable fallback: <= 60 days, zero penalty) | The contract only permits termination for cause under material breach; termination for convenience is omitted. | ❌ SILENT | Not Found / Silent |
| **REQ-05** | Termination Assistance / Transition | 60 days support, no additional fee (acceptable fallback: 30 days support at standard T&M rates) | Customer is granted 14 days to self-export data using native tools, after which data may be permanently deleted. | ⚠️ DEVIATION | Section 5.3: Customer shall have fourteen (14) days to self-export Customer Data using native tools, after which Vendor may permanently delete all stored records. |
| **REQ-06** | Payment Terms | Net 60 days (acceptable fallback: Net 45 days) | Payment is required within 30 calendar days from the invoice date, billed annually in advance. | ⚠️ DEVIATION | Section 3.2: All undisputed fees shall be invoiced annually in advance. Invoices are payable within thirty (30) calendar days from the date of the invoice. |
| **REQ-07** | Price Escalation Cap | <= 3% or CPI annually (acceptable fallback: <= 5% flat cap annually) | Vendor reserves the right to increase annual subscription fees by up to 7.0%. | ⚠️ DEVIATION | Section 3.3: Upon the conclusion of the Initial Term or any Renewal Term, Vendor reserves the right to increase annual subscription fees by up to seven percent (7.0%) upon forty-five (45) days prior written notice. |
| **REQ-08** | Mutual Indemnification | Uncapped IP infringement and data protection indemnity (acceptable fallback: Capped at 3x annual contract value) | The agreement contains no indemnification clause protecting Customer against third-party intellectual property infringement or data breaches. | ❌ SILENT | Not Found / Silent |
| **REQ-09** | Limitation of Liability Cap | 1x to 2x aggregate annual fees mutual liability threshold (acceptable fallback: Fees paid in preceding 12 months) | Vendor's liability is capped at fees paid in the preceding 12 months, but the cap is strictly unilateral and does not protect Customer. | ⚠️ DEVIATION | Section 11.2: EXCEPT FOR BREACHES OF CONFIDENTIALITY UNDER SECTION 9, VENDOR'S TOTAL AGGREGATE LIABILITY ARISING OUT OF OR RELATED TO THIS AGREEMENT SHALL BE LIMITED STRICTLY TO THE FEES ACTUALLY PAID BY CUSTOMER IN THE TWELVE (12) MONTHS PRECEDING THE CLAIM. |
| **REQ-10** | Governing Law & Jurisdiction | State of Delaware or New York (acceptable fallback: State of Customer headquarters) | Governed by Delaware law with personal jurisdiction in Delaware courts. | ✅ MET | Section 14.1: This Agreement and any dispute arising hereunder shall be governed by, and construed in accordance with, the laws of the State of Delaware, without regard to its conflict of law principles. Both parties consent to personal jurisdiction within Delaware courts. |

---

### Actionable Findings & High-Exposure Items

* **[REQ-02] SLA Service Credits** (Clause Missing (Silent)):
  * *Contract Term:* No financial remedy or service credit mechanism is provided for downtime or failure to meet availability targets.
  * *Required Standard:* >= 10% monthly credit per 0.5% outage or escalating fee credit schedule
  * *Exposure Risk:* Absence of a service credit mechanism leaves the Customer without direct contractual or financial recourse when availability drops below 99.9%.

* **[REQ-03] Auto-Renewal Notice Window** (Policy Deviation):
  * *Contract Term:* Non-renewal notice must be delivered at least 15 days prior to term expiration.
  * *Required Standard:* >= 60 days prior notice (acceptable fallback: 45-60 days prior notice)
  * *Exposure Risk:* A 15-day non-renewal notice window severely compresses the evaluation period, creating operational risk of unintended automatic renewal for an additional 12-month period.

* **[REQ-04] Termination for Convenience** (Clause Missing (Silent)):
  * *Contract Term:* The contract only permits termination for cause under material breach; termination for convenience is omitted.
  * *Required Standard:* Permitted with <= 30 days written notice (acceptable fallback: <= 60 days, zero penalty)
  * *Exposure Risk:* Without termination for convenience, Customer is contractually committed to full 12-month periods with no mechanism to exit early due to budget cuts or strategic pivots.

* **[REQ-05] Termination Assistance / Transition** (Policy Deviation):
  * *Contract Term:* Customer is granted 14 days to self-export data using native tools, after which data may be permanently deleted.
  * *Required Standard:* 60 days support, no additional fee (acceptable fallback: 30 days support at standard T&M rates)
  * *Exposure Risk:* A 14-day self-export window without active vendor transition assistance poses high data loss and business continuity risks during offboarding.

* **[REQ-06] Payment Terms** (Policy Deviation):
  * *Contract Term:* Payment is required within 30 calendar days from the invoice date, billed annually in advance.
  * *Required Standard:* Net 60 days (acceptable fallback: Net 45 days)
  * *Exposure Risk:* Net 30 days deviates from enterprise cash flow guidelines requiring Net 60 or Net 45 days, accelerating accounts payable outflows.

* **[REQ-07] Price Escalation Cap** (Policy Deviation):
  * *Contract Term:* Vendor reserves the right to increase annual subscription fees by up to 7.0%.
  * *Required Standard:* <= 3% or CPI annually (acceptable fallback: <= 5% flat cap annually)
  * *Exposure Risk:* A 7.0% annual increase exceeds the enterprise acceptable cap of 5%, exposing the organization to compounding price escalations upon renewal.

* **[REQ-08] Mutual Indemnification** (Clause Missing (Silent)):
  * *Contract Term:* The agreement contains no indemnification clause protecting Customer against third-party intellectual property infringement or data breaches.
  * *Required Standard:* Uncapped IP infringement and data protection indemnity (acceptable fallback: Capped at 3x annual contract value)
  * *Exposure Risk:* Complete lack of vendor indemnification exposes the Customer to direct liability and defense costs should the vendor's software infringe third-party IP rights.

* **[REQ-09] Limitation of Liability Cap** (Policy Deviation):
  * *Contract Term:* Vendor's liability is capped at fees paid in the preceding 12 months, but the cap is strictly unilateral and does not protect Customer.
  * *Required Standard:* 1x to 2x aggregate annual fees mutual liability threshold (acceptable fallback: Fees paid in preceding 12 months)
  * *Exposure Risk:* While the 12-month cap amount meets fallback scale, the limitation is non-mutual, leaving Customer exposed to uncapped liability while strictly limiting Vendor's exposure.

---
*Report automatically compiled by Enterprise Contract Compliance Engine.*
