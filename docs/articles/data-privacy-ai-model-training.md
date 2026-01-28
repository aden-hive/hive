# Data Privacy and AI Model Training

Most sophisticated AI agents are powered by AI models. But, training AI models involves a vast amount of data, some of which may contain sensitive and personal information, — posing the risk of breaking data privacy.

A typical example is a bank that wishes to train an AI model that can detect fraudulent transactions.

National and international regulators require specific standards to be upheld by software developers.

Hence the need for methodologies and approaches utilised to mitigate the risk of breaking data privacy, collectively referred to as _Privacy-Enhancing Technologies_ (PETs).

As listed in the [United Nations Guide On Privacy-Enhancing Technologies](https://unstats.un.org/bigdata/task-teams/privacy/guide/2023_UN%20PET%20Guide.pdf), PETs include: secure multi-party computations, homomorphic encryption, differential privacy, synthetic data, distributed (or federated) learning, zero-knowledge proofs, trusted execution environments (or secure enclaves).


## Decentralized AI Training

Other than the risk to breaking privacy, developers and interested parties are also concerned about centralization of AI training, especially _Large Language Models_ (LLMs) — which is dominated by giant tech companies such as Google, OpenAI, and Anthropic (the main advantage being access to GPUs). 

Although mostly specializing in LLMs, researchers outside well-known tech-giants have recently focused on decentralizing AI training.

Such training involves independent nodes of a network training local models, which get aggregated into one _global model_ via a trusted execution environment (TEE).

- [Nous Research](https://nousresearch.com/): An open-source AI training and research movement, whose mission is to create and democratize access to the world's best intelligence.[^1] Creators of [Psyche](https://psyche.network/runs) and the _Distributed Training Optimizer_ (DisTro).
- [Prime Intellect](https://www.primeintellect.ai/): A company dedicated to building infrastructure for decentralized AI development at scale. Released [OpenDiLoCo](https://www.primeintellect.ai/blog/opendiloco), an open-source framework for globally distributed low-communication training.
- [Pluralis Research](https://blog.pluralis.ai/about): An Australian machine learning research group tackling "decentralized training with an approach called _Protocol Learning_, — which is described as “low-bandwidth, heterogeneous multi-participant, model-parallel training and inference".''[^2] Model ownership and parallelism is one of the group's main focus — even reflected in one of their published [papers](https://arxiv.org/pdf/2506.01260).
- [Templar](https://docs.tplr.ai/research/templar-paper/): An incentive-driven marketplace for decentralized AI tasks on a subnet of the [Bittensor](https://bittensor.com/about)[^3] protocol. Research efforts include _incentivizing learning of LLMs_ even as published in the "[Incentivizing Permissionless Distributed Learning of LLMs](https://docs.tplr.ai/papers/templar_paper.pdf)" paper.
- [Gensyn](https://www.gensyn.ai/): A protocol focused on verification of AI-related workloads, enabling users to submit training requests to the network — to be fulfilled by untrusted _compute_ providers — and ensure that those requests were executed as promised. Its mission is "to build infrastructure for trustworthy, distributed AI compute."[^2] Gensyn’s first implementation in its stack is a training system called [RL Swarm](https://docs.gensyn.ai/testnet/rl-swarm) — a decentralized coordination mechanism for post-training reinforcement learning.

There are other notable projects, also aiming at decentralization of AI model training: [FortyTwo](https://fortytwo.network/), [Ambient](https://ambient.xyz/about), [Flower Labs](https://flower.ai/), [Macrocosmos](https://docs.macrocosmos.ai/), and [Flock.io](https://train.flock.io/).




## Private-Enhancing Technologies - An Overview

Since different entities like banks and healthcare companies own separate datasets, that are governed by regulatory standards — such as the Protection of Personal Information ([PoPI](https://popia.co.za/)) Act, General Data Protection Regulation ([GDPR](https://gdpr-info.eu/)), California Consumer Privacy Act ([CCPA](https://cppa.ca.gov/regulations/)), — AI Training is by necessity collaborative in development, and takes advantage of mutual sharing of AI models.



### Secure Multi-Party Computations

Secure Multi-Party Computations (SMPC) is a cryptographically privacy-preserving approach that allows multiple, mutually distrusting parties to jointly compute an agreed-on function $f$ on input data $(x_1, \dots , x_t)$ that they provide to the computation, yet are unwilling to disclose the input data to others. — And thus, every other party $P_j$ can only see ciphertexts of $(x_1, \dots , x_t)$ for all $i \not= j$. 

![Figure: SMPC - Joint-computation of a agreed upon function](/docs/articles/img/smpc-joint-computation.png)

Essential components of SMPC are secret sharing schemes, commitment schemes, and proof/verification crypto-systems. Implementations of these schemes may involve _garbled circuits_, _oblivious transfers_, or _homomorphic encryption_.



### Homomorphic Encryption

Homomorphic Encryption (HE) allows direct computation (execution of addition and multiplication operations) on encrypted data.

This enables parties to outsource computations on encrypted data — They simply provide the necessary input data and receive computation outputs without disclosing any sensitive data.

Protocols using Homomorphic Encryption ensure that no party other than the provider of the input data learns anything about the data under computation.

The encryption deployed in HE-based protocols can be either symmetric or asymmetric, while some can enable multiple parties to participate — for instance, _Regev Encryption_[^4] and _Dual Regev Encryption_[^5] are asymmetric, while _Domingo Ferrer_[^6] encryption scheme is symmetric HE. 



### Federated Learning

Federated learning (FL) is "a machine learning setting where many clients (e.g. mobile devices or whole organizations) collaboratively train a model under the orchestration of a central server (e.g. service provider), while keeping the training data decentralized."[^8]  

It aims at minimising collection of data across entities participating in training a common global model. It therefore helps mitigate privacy risks and related costs prevalent in traditional, centralized machine learning and data science approaches.

Successful training of an accurate global model involves computational off-loading for model updates and model aggregation. 

Federated Learning can be implemented in three modes:

- _Horizontal FL_ mode, which involves datasets with similar features allowing for an easy lateral model transfer.
- _Vertical FL_ mode, where data samples are similar across participating entities yet with differing features — therefore requires an aggregated description of data entries. 
- _Federated Transfer Learning_ mode, which uses transfer of _learning techniques_ (sometimes actual models).

An FL mode can be chosen by the system designer in line with the computing power of target clients and end-users. 



### Differential Privacy

Although Federated Learning protects privacy by not sharing raw data, the information transfer during its model update process can still potentially leak user privacy.

Differential Privacy (DP) is "an advanced privacy protection technology, _that_ introduces random noise during data queries or model updates, further enhancing the privacy protection capability of Federated Learning."[^7] 

DP has become the _de facto_ standard for protecting user privacy in statistics-related computations. It allows analysis and release of datasets without compromising individual privacy. 



### Synthetic Data

Synthetic Data (SD), as a PET, is an output privacy technique that provides privacy guarantees when releasing information to a third party. 

It relies on transforming sensitive datasets into new datasets but with similar statistical properties, without revealing personal information contained in the original dataset.

Therefore, Synthetic Data is artificial data designed to mimic real-world data. 

Despite being artificially generated, synthetic data retains the underlying statistical properties of the original data it is based on. As such, synthetic datasets can supplement or even replace real datasets.[^9] 

As noted in the UN PET guide, Synthetic Data aims to meet two objectives:[^10] 

1. _Utility for statistical analysis_: one should be able to study the statistics of the original data, potentially including complicated patterns, directly from the synthetic data.

2. Privacy: the synthetic data should not reveal information about individuals from the original dataset.

SD is therefore best suited for AI models trained on sensitive and confidential data such as held by banks and hospitals.



### Zero-Knowledge Proofs

Zero-Knowledge Proofs (ZKP) is a privacy-enhancing technology commonly deployed in cryptosystems that require some entity to prove knowledge of a secret, while allowing other independent entities to verify the proof.

"Zero knowledge (ZK) refers to a class of cryptographic technologies that allows one party (called the prover) to convince another party (called the verifier) of the veracity of a claim that depends on secret information known to the prover without revealing those secrets to the verifier."[^10] 

Application of ZKPs in the context of AI model training focuses on the verification of training processes while maintaining data confidentiality.

Thompson Prasley proposed, in his [2024 paper](https://itjournal.org/index.php/itjournal/article/download/25/27/65), "a framework where ZKPs are utilized to validate the execution of machine learning algorithms on private datasets, ensuring that the outcomes are correct and trustworthy without compromising data privacy."[^11] 

A lot of work has been done on the application of ZKPs in machine learning, culminating in the concept of a ZKML. [Zhizhi Peng et al.](https://arxiv.org/pdf/2502.18535) made a survey of research done from June 2017 to December 2024, in which they outline ZKP algorithmic setups of ZKMLs under three categories: verifiable training, verifiable inference, and verifiable testing.



### Trusted Execution Environments

Trusted Execution Environment (TEE) is a hardware-isolated area in a microprocessor that enables secure execution of applications, thereby ensuring confidentiality and integrity of data and code. 

Being a secure and isolated area, a TEE provides a platform — within a computing system — for running code and accessing data in a protected way.

[Tim Geppert et al.](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2022.930741/full) describe a TEE as a "security technology that promises to mitigate attacks on cloud systems and therefore lowers the barriers to cloud computing adoption by organizations."

Collaboration via TEEs enable secure model training by allowing multiple parties to collaborate on model training, without exposing their data.

Here's how this type of a setup works, "each participant encrypts their data and sends it to a TEE, where model training occurs in a protected environment."[^12] 

TEEs therefore ensure that no data is leaked or shared between parties during the training process — Allowing organizations to retain full control over their data while benefiting from collaborative model training.

Examples of popular TEEs are: Intel Software Guard Extensions (SGX) and AMD TrustZone. 

"More recently, AWS Nitro Enclaves offer a hypervisor-based approach to TEEs which offers an alternative security model but allows for very flexible deployment."[^10] 



### PET Combinations: Pros and Cons

A single PET is practically insufficient to ensure _confidentiality_, _data privacy_ or build _user trust_.

It generally takes a combination of _two_ to _three_ PETs to achieve _all the above_.

A secure Federated Learning protocol may be realised only when coupled with an SMPC, whereas an SMPC may have to utilise _Homomorphic Encryption_, — more especially where confidentiality is paramount.

Yet, the more complex the system design the challenging it is to retain _efficiency_ and _performance_.

Below is a brief tabulation of the pros and cons of the most common PET combinations. 

| PET Combo | Pros | Cons |
| --------- | ---- | ---- |
| SD + DP   | Reduces re-identification risks | May introduce bias or degrade model accuracy |
| SMPC + HE | Ensures secure computations | High computational costs |
| SMPC + FL | Mitigates data leakage risks | High communication overheads |



## PET Case Studies

The best way to gain insight into the different types of PETs, while demonstrating their applications in AI model training, is through case studies.

Below, we briefly outline case studies independently carried out by two organisations: United Nations PET Lab, and the Centre for Information Policy Leadership (CIPL).



### UN PET Case Studies

The [UN PET Guide](https://unstats.un.org/bigdata/task-teams/privacy/guide/2023_UN%20PET%20Guide.pdf) includes eighteen case studies with some of them utilising more than one PETs. 

The UN PET case studies were dominantly of a statistical theme, with a majority focusing on Data Analysis and Data Processing, only a few purely on Privacy Preservation, and one on Auditing.

Of all $18$ projects: $9$ are but _proofs of concepts_, $5$ _pilots_, $3$ have gone to _production_, and only $1$ is a _concept_. 

The table below summarises the usage of PETs in the 18 case studies of the [UN Guide on PETs](https://unstats.un.org/bigdata/task-teams/privacy/guide/2023_UN%20PET%20Guide.pdf). 

| Case Study Type  | Case Studies | SMPC | HE | DP | SD | FL | ZKP | TEE |
| ---------------- | :----------: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| Proof of Concept | 9 | 5 | 3 | 4 | 1 | 3 | 0 | 2 |
| Concept | 1 | 1 | 1 | 0 | 0 | 1 | 0 | 0 |
| Pilot | 5 | 4 | 2 | 1 | 1 | 0 | 0 | 0 |
|Production | 3 | 1 | 0 | 1 | 0 | 0 | 0 | 1 |
| **Total** | **18** | **11** | **6** | **6** | **2** | **4** | **0** | **3** |

From the above table, we note that SMPC is most prevalent, with HE and DP as the second most popular, then FL used in $4$ projects, followed by TEE. 

None of the $18$ PET case studies deploys any Zero-Knowledge Proof.



### CIPL PET Case Studies

The Centre for Information Policy Leadership (CIPL) published a [report](https://www.informationpolicycentre.com/uploads/5/7/1/0/57104281/cipl_pets_and_ppts_in_ai_mar25.pdf) in March 2025, which provides a "_snapshot in time_ of the current state of development and use of PETs in the blossoming AI field."[^12] 

The report also contains brief details of $19$ case studies on various PET combinations in AI training projects.

As per its title, the report explores how PETs can enable usage of privately owned data while operationalizing privacy by design. 

The case studies cover AI model training with applications ranging from — _LLMs_ and _small language models_ to accuracy improvement of _neural networks_ — as well as from _developing AI reasoning in Mathematics_ to _fraud detection models_.

The last case study, which focuses on _Privacy and Utility_, trains "AI to anonymize data sets without sacrificing data utility."[^12] 

The table below depicts the number of times each PET was utilised in the case studies, together with the number of times each PET was paired with another.

The asterisk indicates that the PET was also deployed in at least one triple PET combinations (not counted in the reflected number of pairs).

![Figure: CIPL Case Studies Analysis](/docs/articles/img/cipl-case-studies-analysis.png)



## PET Events And Standardization 

The [OECD](https://www.oecd.org/en.html) (Organisation for Economic Co-operation and Development) is a "forum and knowledge hub for data, analysis and best practices in public policy" — Working with over 100 countries across the world to help shape better policies for better lives.

OECD published a report — in June 2025, titled "[Sharing trustworthy AI models with privacy-enhancing technologies](https://www.oecd.org/content/dam/oecd/en/publications/reports/2025/06/sharing-trustworthy-ai-models-with-privacy-enhancing-technologies_5df6fd05/a266160b-en.pdf) — which highlights two primary _use case archetypes_ mainly emanating from two of OECD's expert workshops, one on PETs and the other on AI, held between May and July 2024.

- Use Case _Archetype 1_: Enhancing AI model performance through minimal and confidential use of input and test data.

- Use Case _Archetype 2_: Enabling co-creation and sharing of AI models.

NIST is making efforts towards standardization of PETs by involving Cryptographers and Engineers participating in workshops, as well as contributing to drafts of standards:

- NIST held a Workshop on Privacy-Enhancing Cryptography ([WPEC2024](https://csrc.nist.gov/events/2024/wpec2024)) in September, 2024. The videos of the workshop can be accessed at the [NIST video gallery](https://www.nist.gov/video-gallery/search?k=wpec).

-  NIST released a draft titled, "[Toward a PEC Use-Case Suite](https://csrc.nist.gov/CSRC/media/Projects/pec/documents/suite-draft1.pdf)", which provides a list of _Privacy-Enhancing Cryptography Primitives/Techniques_: 
   -  Zero Knowledge Proofs (ZKPs) — Prove knowledge of a secret solution to a problem, without revealing the solution. 
   -  Secure Multiparty Computation (SMPC) — Jointly compute a function over inputs distributed across several parties, without each party revealing their input. 
   -  Group and ring signatures — Produce an unforgeable digital signature, convincingly exhibiting that it has been signed by an unrevealed member of a group. 
   -  Functional encryption — Decrypt a function (as specified by a decryption key) of a plaintext that has been encrypted, without learning the clear plaintext. 
   -  Fully-Homomorphic Encryption (FHE) — Compute over encrypted data, without learning the plaintext input/output, but ensuring the intended functional transformation. 
   -  Private Set Intersection (PSI) — Determine the intersection of sets held by multiple parties, without revealing the non-intersecting components. 
   -  Private Information Retrieval (PIR) — Query a key-value database, with the database owner being assured that only one element was queried but not learning which. 
   -  Searchable Encryption — Search for a keyword in a database of encrypted documents, obtaining the resulting documents without revealing the keyword. 
   -  Blind signatures — Obtain a signature, from a trusted party, without revealing what document has been signed.

See also this [post](https://csrc.nist.gov/projects/pec/pec-tools) for _PEC tools_ with illustrative diagrams. 



## Practicality of PETs 

As reflected by the UN case studies, where $3$ out of $18$ projects have gone to production, while $5$ other projects are at the pilot stage, the mission to attaining privacy in AI model training is becoming a reality. 

Albeit, there are exceptional cases, in the form of the _Homomorphic Encryption-based_ PETs. 

Amongst the UN PET case studies, no project utilising HE has gone to production. 

Only $2$ projects out of $6$ deploying HE are at the pilot stage, while $3$ are just _proof of concepts_.  



### Challenges with HE PETs

Research shows that Homomorphic Encryption has a few limitations and implementation challenges.

HE is based on Homomorphic Cryptography (HC) which has remarkable benefits, making it suitable for use in a number of fields such as; _cloud computing_, _healthcare_, _banking_, _e-voting systems_, _machine learning_, _the IoT_, and more.

Yet, after practical implementation of HE using prominent HE libraries, [Khalil Hariss et al.](https://www.sciencedirect.com/science/article/pii/S1574013725000917) report that Homomorphic Cryptography faces certain limitations and challenges including:[^13] 

- Limited Accuracy: Which is often caused by the introduction of some noise in the encrypted data during the HE process, — which in turn, can affect the accuracy of the computation outputs.
- Limited Scalability and Interoperability: Especially when dealing with large datasets or complex computations due to high computation time and memory requirements.
- High Computational Requirements: The computational intensity and complexity of Homomorphic Cryptography schemes necessitate a substantial computing quantity in order to perform computations on the encrypted data.
- Limited Functionality: HC restricts the kinds of computations that can be carried out or supports a small number of operations, which proves to be a challenging task to integrate into other real-world applications.

Nonetheless, [Khalil Hariss et al.](https://www.sciencedirect.com/science/article/pii/S1574013725000917) continued to state: "The future of HC algorithms is very promising and can modernize the way sensitive data is handled to enable secure computation in a wide range of applications."

Consequently, we can conclude that the HE PET has great potential which awaits a few improvements on the practicality of HC. 


## Conclusion

Recognising the need to protect data privacy when training AI models, this report captures technologies and methodologies to achieve this goal — collectively known as _Privacy-Enhancing Technologies_.

It's apparent that this is a vast area of research owing to the diversity of the AI models that need to be trained. 

Researchers are not only concerned about _privacy_ of AI model training, but also wish to see training reach the next level of _scalability_ and _decentralization_.

Despite the many challenges and existing cryptographic limitations of PETs, standards are being developed, new frameworks are proposed for the more complex PETs (e.g., ZKPs). 

And, researchers continue to find better methodologies to solve real-world problems, and thus advance developments towards performant, efficient and useful AI models.






## Footnotes

[^1]: Nous Research  https://nousresearch.com/

[^2]: Lucas Tcheyan, "Decentralized AI Training: Architectures, Opportunities, and Challenges," Galaxy, (September, 2025) https://www.galaxy.com/insights/research/decentralized-ai-training

[^3]: According to CoinMarketCap, "Bittensor (TAO) is a decentralized blockchain protocol designed to incentivize global collaboration in artificial intelligence (AI) development through a peer-to-peer marketplace for machine learning models," https://coinmarketcap.com/cmc-ai/bittensor/what-is/


[^4]: Section 3.3 of "The Learning with Errors Problem: Introduction and Basic Cryptography," MIT CS 294 Lecture Notes, https://people.csail.mit.edu/vinodv/CS294/lecture1.pdf

[^5]: Definition 3.3 in "Eﬃcient and Tight Oblivious Transfer from PKE with TightMulti-User Security," written by Saikrishna Badrinarayanan, Daniel Masny, and Pratyay Mukherjee, (Aug, 2021), https://usa.visa.com/content/dam/VCOM/regional/na/us/about-visa/documents/meot.pdf

[^6]:  Josep Domingo-Ferrer, "A provably secure additive and multiplicative privacy homomorphism," in: Proceedings of the 5th Int. Conference on Information Security, ISC ’02, Springer-Verlag, London, UK, (2002), pp. 471–483. https://ics.uci.edu/~projects/295d/papers/provably-secure-additive-and-multiplicative-privacy-homomorphism.pdf

[^7]: Fangfang Shan et al., "Differential Privacy Federated Learning: A Comprehensive Review," (IJACSA) International Journal of Advanced Computer Science and Applications, Vol. 15, No. 7, (2024) … https://thesai.org/Downloads/Volume15No7/Paper_22-Differential_Privacy_Federated_Learning.pdf

[^8]: Peter Kairouz, H. Brendan McMahan, Brendan Avent, et al., "Advances and Open Problems in Federated Learning," (2021) https://arxiv.org/pdf/1912.04977

[^9]: Rina Diane Caballar, IBM Document — "What is synthetic data?" https://www.ibm.com/think/topics/synthetic-data

[^10]: United Nations Guide On Privacy-Enhancing Technologies, (2023) https://unstats.un.org/bigdata/task-teams/privacy/guide/2023_UN%20PET%20Guide.pdf

[^11]: Thompson Prasley, "Zero-Knowledge Proofs for Verifiable AI Model Training," International IT Journal of Research (IITJR) Vol. 2, Issue 2, Apr- Jun, (2024) https://itjournal.org/index.php/itjournal/article/download/25/27/65

[^12]: CIPL Report—"Privacy-Enhancing and PrivacyPreserving Technologies in AI: Enabling Data Use and Operationalizing Privacy by Design and Default" (March 2025) https://www.informationpolicycentre.com/uploads/5/7/1/0/57104281/cipl_pets_and_ppts_in_ai_mar25.pdf

[^13]:  Khalil Hariss et al., "Homomorphic cryptography: Challenges and perspectives" (2025) https://www.sciencedirect.com/science/article/pii/S1574013725000917 
