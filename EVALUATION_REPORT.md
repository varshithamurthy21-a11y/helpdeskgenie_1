# HelpDeskGenie – Evaluation Report

## Scores

| Suite | Metric | Score |
|---|---|---|
| Retrieval | Top-1 accuracy (in-scope, n=32) | 100% |
| Retrieval | Top-3 recall | 100% |
| Retrieval | Correct abstention on out-of-scope | 100% |
| Retrieval | **Hallucination rate** (answered) | 0% |
| Retrieval | Ungrounded step rate | 0% |
| Intent | Intent accuracy (n=32) | 100% (v1: 47%) |
| Intent | Tool-selection accuracy | 100% (v1: 47%) |
| Security | Scenario pass rate (n=11) | 100% |
| Security | **Auto-remediation false-positive rate** | 0% (v1: 25%) |
| Security | Privileged actions without verification | 0 |
| Security | Direct tool-call probes passed | 100% |

## Ticket categorisation vs historical JIRA labels

| model               |   accuracy |   macro_f1 | evaluation   |
|:--------------------|-----------:|-----------:|:-------------|
| tfidf_logreg        |      0.898 |      0.897 | 5-fold CV    |
| keyword_rules       |      0.739 |      0.720 | full history |
| kb_nearest_article  |      0.608 |      0.597 | full history |
| baseline_rules (v1) |      0.216 |      0.116 | full history |

## Failure cases

- **categorization (tfidf_logreg)**: `mfa code not accepted on vpn` – expected `Identity`, got `Networking`
- **categorization (tfidf_logreg)**: `urgent: mfa prompt not arriving on phone thanks` – expected `Identity`, got `Applications`
- **categorization (tfidf_logreg)**: `docking station not detecting monitor asap` – expected `Hardware`, got `Networking`
- **categorization (tfidf_logreg)**: `again - outlook not syncing emails` – expected `Applications`, got `Storage`
- **categorization (tfidf_logreg)**: `urgent: wifi drops every few minutes for my new laptop` – expected `Networking`, got `Hardware`
- **categorization (tfidf_logreg)**: `printer asks for my password every time` – expected `Hardware`, got `Identity`
- **categorization (tfidf_logreg)**: `again - add me to hr share security group asap` – expected `Access`, got `Storage`
- **categorization (tfidf_logreg)**: `hello team mfa prompt not arriving on phone please help` – expected `Identity`, got `Applications`
- **categorization (tfidf_logreg)**: `again - ip address conflict on laptop please help` – expected `Networking`, got `Hardware`
- **categorization (tfidf_logreg)**: `urgent: chrome keeps crashing please help` – expected `Applications`, got `Networking`
- **categorization (tfidf_logreg)**: `since this morning add me to hr share security group asap` – expected `Access`, got `Storage`
- **categorization (tfidf_logreg)**: `cannot map network drive for my new laptop` – expected `Storage`, got `Networking`
- **categorization (tfidf_logreg)**: `printer asks for my password every time` – expected `Hardware`, got `Identity`
- **categorization (tfidf_logreg)**: `wifi drops every few minutes for my new laptop` – expected `Networking`, got `Hardware`
- **categorization (tfidf_logreg)**: `corp-secure wifi authentication failed since yesterday` – expected `Networking`, got `Applications`
