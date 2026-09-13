# Iterative expense categorization

> **Status:** Post-v1 research. V1 deliberately contains no learned classifier or reusable Counterparty categorization rules; it delegates uncategorized Transactions to an external personal agent through the MCP adapter.

## Conclusion

A local personalized classifier is practical on the Synology DS225+. The useful distinction is **classifier versus LLM**: a sparse text classifier or nearest-example model is tiny and fast on CPU, whereas running a generative LLM locally is a substantially heavier optional fallback.

The recommended v1 experiment is:

1. Exact Category Rules and accepted Counterparty history.
2. A character/word n-gram classifier trained only from reviewed labels.
3. Abstention below a measured confidence threshold, producing Pending Review rather than a guess.
4. A pluggable cloud LLM fallback for unseen or low-confidence Counterparties, receiving only the bounded categorization payload.

Do not fine-tune an LLM for the initial three-month dataset. Retraining a small classifier from all accepted labels is simpler, reproducible, and cheap enough that true online mutation is unnecessary at this scale.

## Hardware fit

Synology specifies the DS225+ with a 64-bit, four-core Intel Celeron J4125 running at 2.0 GHz base / 2.7 GHz turbo. Synology officially lists 2 GB built in and a 6 GB supported maximum; this project can use the user's reported 18 GB configuration but should not require it. [Synology product specification](https://global.download.synology.com/download/Document/Hardware/ProductSpec/DiskStation/25-year/DS225+/enu/Product_Spec_DS225+_enu.pdf)

This CPU is sufficient for sparse text classification, fastText, and occasional small embedding inference. A local generative LLM should be treated as an experiment rather than a v1 dependency: RAM capacity alone does not make generation responsive on this low-power CPU, and latency must be benchmarked on the actual NAS.

## Candidate local approaches

### 1. Counterparty memory and explicit rules

This is the strongest baseline, not a machine-learning model. An accepted mapping such as `YA KUN → Food & Drink` can categorize repeated activity exactly, while known variable Counterparties such as Amazon can abstain or use more specific rules.

Advantages:

- Deterministic and explainable.
- Learns immediately from explicit “always use this Category” actions.
- No confidence calibration or model runtime.

Limitation: it does not generalize to genuinely unseen Counterparties.

### 2. TF-IDF n-grams plus logistic regression

Scikit-learn's `TfidfVectorizer` supports word and character n-grams, and its documentation recommends sparse text features with fast linear classifiers. Character n-grams are useful for noisy provider descriptions and variants such as `YA KUN`, `YAKUN`, and location suffixes. [Scikit-learn text feature extraction](https://scikit-learn.org/stable/modules/feature_extraction.html) · [TfidfVectorizer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html) · [Sparse text classification example](https://scikit-learn.org/stable/auto_examples/text/plot_document_classification_20newsgroups.html)

Advantages:

- Very small CPU and memory requirements for a personal dataset.
- Fast full retraining and inference.
- Inspectable feature weights.
- Logistic regression can provide scores for an abstention threshold.

Limitation: lexical generalization is weaker for an unseen merchant whose name has no relationship to labeled examples.

**Recommended first learned baseline.** Full retraining from the complete accepted-label dataset is preferable to mutating it one transaction at a time.

### 3. HashingVectorizer plus SGDClassifier

Scikit-learn documents `HashingVectorizer` as a stateless text representation suitable for streaming, and `SGDClassifier.partial_fit` supports incremental mini-batch learning. Its official out-of-core example combines these components for online text classification. [HashingVectorizer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.HashingVectorizer.html) · [SGDClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.SGDClassifier.html) · [Out-of-core text classification](https://scikit-learn.org/stable/auto_examples/applications/plot_out_of_core_classification.html)

Advantages:

- Genuine incremental updates.
- Fixed feature space as new merchant tokens appear.
- Low resource use.

Limitations:

- Update order and learning-rate history affect the resulting model.
- Harder to reproduce and roll back than full retraining.
- New Category classes require deliberate handling; scikit-learn requires the possible classes on the initial `partial_fit` call.
- Probability estimates and thresholds require care and potentially calibration. Scikit-learn warns that classifier probabilities can be poorly calibrated. [Probability calibration](https://scikit-learn.org/stable/modules/calibration.html)

**Useful benchmark, but not the preferred v1 lifecycle.** With only personal transaction history, full retraining is simpler.

### 4. Naive Bayes or passive-aggressive online classifiers

Scikit-learn includes Multinomial Naive Bayes, Perceptron, and passive-aggressive models among classifiers that support incremental learning in its out-of-core text example. [Out-of-core text classification](https://scikit-learn.org/stable/auto_examples/applications/plot_out_of_core_classification.html)

These are inexpensive baselines, but should be selected only by evaluation against the user's temporal holdout. They offer no product-level advantage over the simpler recommended baseline unless they produce better precision and coverage.

### 5. fastText supervised classification

fastText is designed as a lightweight text classification library for ordinary hardware. Its supervised API returns labels and probabilities, supports word n-grams and character subwords, and can quantize models to reduce memory. Character subwords improve robustness to misspellings and unseen word forms. [fastText project](https://fasttext.cc/) · [Python supervised API](https://fasttext.cc/docs/en/python-module.html) · [Subword explanation](https://fasttext.cc/blog/2017/10/02/blog-post.html)

Advantages:

- Lightweight CPU inference.
- Character subwords suit noisy merchant names.
- Compact model artifacts.

Limitations:

- Adds a separate native dependency.
- The straightforward workflow is periodic retraining rather than durable online updates.
- Must still be evaluated and thresholded on Billzebub's categories.

**Reasonable third benchmark, not necessary for the first implementation.**

### 6. Local sentence embeddings plus nearest neighbors or a linear classifier

Sentence Transformers can run locally on CPU and supports semantic similarity and classification use cases. Its ONNX backend and int8 model quantization can improve CPU inference; the project recommends benchmarking backend choices on the actual workload. [Sentence Transformers usage](https://sbert.net/docs/sentence_transformer/usage/usage.html) · [Semantic search](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html) · [CPU/ONNX efficiency](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)

Advantages:

- Every accepted example immediately becomes retrievable without classifier retraining.
- Better potential semantic generalization than lexical n-grams.
- A small corpus needs no vector database; an in-memory similarity scan is enough.

Limitations:

- Heavier dependency and inference than sparse text models.
- Generic embeddings may not understand local merchant names or personal category preferences.
- Similarity is not calibrated classification confidence.

**Optional second-stage experiment.** Test a small quantized embedding model only if lexical classification misses too many unseen Counterparties.

### 7. A local generative LLM

A small quantized LLM could perform zero-shot categorization from the Category definitions and a few accepted examples. It may help with unseen merchants, but it is not the iterative personal classifier: the accepted labels remain examples in its prompt or retrieval context unless the model itself is fine-tuned.

On the DS225+, this should remain optional until measured. The likely constraint is CPU inference latency rather than the user's available RAM. No v1 correctness or availability requirement should depend on it.

## Recommended training lifecycle

### Label provenance

Keep the origin of every Category assignment:

- `user_confirmed`
- `user_corrected`
- `explicit_rule`
- `classifier_predicted`
- `cloud_predicted`

Only the first three are training truth. A prediction left untouched is not an implicit confirmation; otherwise the system trains on its own mistakes.

### Reproducible retraining

1. Preserve all accepted labeled examples.
2. Rebuild the model from the complete accepted set after a configurable number of new labels or on a schedule.
3. Save the training dataset hash, feature configuration, code version, metrics, and model artifact.
4. Keep the previous model available for rollback.
5. Record model version, candidate Categories, and scores with every prediction.

This behaves iteratively to the user while avoiding irreversible `partial_fit` drift.

### Features to evaluate

Start with:

- Canonical Counterparty.
- Raw provider description after removing account/reference identifiers.
- Source type and Financial Account alias.
- Currency.
- Coarse amount bucket.
- Day of week.

Do not require all features. Ablate them during evaluation so the implementation can prove whether context adds value beyond Counterparty text.

### Evaluation

Use a temporal split rather than random leakage:

1. Review and label all three initial months.
2. Train on months one and two.
3. Test on month three.
4. Compare exact Counterparty memory, TF-IDF/logistic regression, hashing/SGD, fastText, and optionally embeddings.
5. Measure per-Category precision/recall and, most importantly, **automatic coverage at the required precision**.
6. Start with predictions as suggestions. Enable automatic assignment only for paths whose held-out precision satisfies the agreed threshold.

The product should abstain when uncertain. Overall accuracy alone can hide failure on infrequent Categories.

## Privacy-oriented cloud fallback

Billzebub should hide providers behind one stateless categorization interface and log exactly which bounded fields were transmitted. Provider policies and model eligibility change, so retention configuration must be verified during deployment rather than inferred from a brand name.

| Provider path | Training and default retention posture | Zero-retention option |
|---|---|---|
| **Amazon Bedrock** | AWS states model providers do not have access to prompts/completions. Its current retention controls distinguish default, provider-sharing, and `none` modes. [Data protection](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html) | `data_retention_mode: none` writes no request/response data to durable storage and does not share it with the model provider, but only models allowing that mode are available. [Data retention](https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html) |
| **Azure-hosted models** | Microsoft states prompts, completions, embeddings, and training data are not available to model providers and are not used to train foundation models without permission. [Azure data privacy](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy) | Approved subscriptions can turn off storage for abuse monitoring; configuration and model support must be checked. |
| **OpenAI API** | API inputs/outputs are not used for training by default. Standard abuse-monitoring logs may contain content and are retained up to 30 days. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data) | Eligible, approved organizations can enable Zero Data Retention for supported endpoints. |
| **Anthropic API** | Commercial API inputs/outputs are not used for training by default and are normally deleted from the backend within 30 days. [Training policy](https://privacy.anthropic.com/en/articles/7996868-is-my-data-used-for-model-training) · [Retention policy](https://privacy.anthropic.com/en/articles/7996866-how-long-do-you-store-personal-data) | Approved organizations may negotiate ZDR for eligible APIs. [Anthropic ZDR](https://privacy.anthropic.com/en/articles/8956058-i-have-a-zero-retention-agreement-with-anthropic-what-products-does-it-apply-to) |
| **Paid Gemini API** | Google states paid-service prompts and responses are not used to improve its products, though limited abuse-monitoring logging applies. Free service content may be reviewed and used for improvement and must not receive sensitive data. [Gemini API terms](https://ai.google.dev/gemini-api/terms) | Approved projects can obtain ZDR subject to feature restrictions; stateless calls and disabled storage are required. [Gemini ZDR](https://ai.google.dev/gemini-api/docs/zdr) |
| **Mistral Scale API** | Mistral states Scale API data is not used for training by default; training control and retention are separate settings. [Mistral privacy controls](https://docs.mistral.ai/admin/monitor-comply/privacy-data-controls) | ZDR is available by approval on the paid Scale plan for stateless API calls. [Mistral ZDR](https://help.mistral.ai/en/articles/323752-can-i-activate-zero-data-retention-zdr) |

### Provider recommendation

- **Strongest straightforward policy:** prefer an AWS Bedrock model that permits enforced `none` retention, if the additional AWS setup is acceptable.
- **Simplest direct API:** OpenAI, Anthropic, paid Gemini, or Mistral can be acceptable for the bounded payload, but their standard offerings generally retain some content temporarily for abuse monitoring unless ZDR is approved.
- **Never use free Gemini API/AI Studio for financial categorization payloads**, because its unpaid-service terms allow submitted content and responses to be used for product improvement and human review.

Even with ZDR, send only the canonical Counterparty and allowed Category labels initially. No cloud provider should receive Source Artifacts, account identity, reference numbers, raw email bodies, or complete Claim descriptions.
