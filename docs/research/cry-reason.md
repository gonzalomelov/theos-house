# Why is he crying, from the sound: ChatterBaby and the open options (issue #161)

Researched Oct 30 2026 from primary sources. The starting point is ChatterBaby from UCLA. The question here is whether any of it can run in the house, so no cry audio leaves the home.

## Answer in one table

| Option | Classes | Published accuracy | Model or code public | Data public | Runs locally | Usable here |
|---|---|---|---|---|---|---|
| ChatterBaby (UCLA, Ariana Anderson's lab) | hungry, fussy, pain | 71.5% three-way, pain recall 0.91, AUC 0.88, out-of-bag on its own data | No. Not found on GitHub or in the paper | No. Kept by UCLA, used for its research | No. The app sends each cry to UCLA's servers | **No** |
| Donate-a-Cry corpus | hungry, tired, discomfort, burping, belly pain (cleaned set) | none from its authors | n/a, data only | Yes, ODbL 1.0, contents DbCL 1.0 | Yes | **Yes, and we trained on it** |
| Baby Chillanto (INAOE, Mexico) | normal, hunger, pain, deaf, asphyxia | many papers, none on a shared public split | No | On request to INAOE, no public terms found | n/a | No: by request only, and half of it is medical |
| CryCeleb 2023 (Ubenwa) | who the baby is, no reason labels | n/a | n/a | CC BY-NC-ND 4.0, gated on Hugging Face | n/a | No: no reason labels, gated, no derivatives |
| Hugging Face "baby cry" models | mostly Donate-a-Cry's classes | model cards report accuracy on random clip splits, one reports 0.38 | Yes, Apache 2.0 on the cards | trained on Donate-a-Cry copies | Yes | Not as is: no grouped held-out test, and our test clips are likely in their training data |
| A Meta audio model | Perception Encoder Audio-Visual (PE-AV), SAM Audio. No cry reason model | n/a | weights on Hugging Face | n/a | heavy | Not tonight: no cry reason head exists, and SAM-class models are off for this item |

So ChatterBaby cannot be used as is: its model is not published and its app is a cloud service. The closest real thing that keeps audio in the house is a classifier trained locally on the one open labeled corpus whose license allows it, Donate-a-Cry. We built that and measured it on a held-out test written before training. It is at chance (results/cry-reason/README.md), so today the sound guess is logged, not said.

## ChatterBaby

- **What it is.** A free app and research program from UCLA (Ariana Anderson's lab, Semel Institute). The site says the models predict "hunger, pain, fussy". Its training data also had colic, scared and separation cries that the app does not predict. https://www.chatterbaby.org/
- **Where the audio goes.** The site says the app "sends the cry to our servers" to remove noise and run the algorithm at UCLA, and that recordings are kept and used for research (development and autism risk). The App Store listing says data is kept "for science" on a HIPAA-compliant server. https://apps.apple.com/app/id1347345855 . This is why it was ruled out in issue #32, and it still is.
- **The paper.** Parga JJ, Lewin S, Lewis J, et al., "Defining and distinguishing infant behavioral states using acoustic cry analysis: is colic painful?", Pediatric Research 87(3):576-580, 2020. DOI 10.1038/s41390-019-0592-4. Open copy: https://escholarship.org/uc/item/3h36c0hh
  - Data: 353 pain cries recorded at vaccinations and ear piercings, 171 fussy and 167 hungry cries labeled by the caretaker and kept only when two more raters agreed (11.8% dropped). 380 colic clips from 64 babies as an outside test.
  - Model: about 6,000 openSMILE features (IS13 ComParE) per 5 s clip, a random forest in R with default settings.
  - Accuracy: 71.5% across the three states, out-of-bag. Pain against the rest: recall 0.91, specificity 0.68, positive predictive value 0.75, AUC 0.88. No held-out test on new babies for the three-way number.
  - The headline "90% for pain" in UCLA's press release is the pain recall, not the three-way accuracy. https://www.uclahealth.org/news/release/app-helps-new-and-deaf-parents-know-when-and-why-their-baby-is-crying
- **Model, code, data.** No repository, model file or dataset release was found, and the paper has no data availability statement we could read. The only audio the paper points to is one child's vaccination clips on YouTube. No license grants any use.
- **Can it run locally.** No. Reproducing it would need its labeled cries, which are not public. The recipe (openSMILE ComParE plus a random forest) is public, so we could rebuild the method, but only on other data.
- **Pain is a medical reading.** The agent must never say a baby is in pain. Even a working pain class could only become "check on him now".

## Open data and models

- **Donate-a-Cry corpus.** Cries recorded by parents in the Donate-a-Cry app (2015), tagged by the parent who uploaded them. The cleaned set has 457 clips from 221 app installs: hungry 382, discomfort 27, tired 24, belly pain 16, burping 8. Clips are about 7 s, 8 kHz phone audio. License ODbL 1.0 for the database, DbCL 1.0 for the contents. A trained model is a Produced Work under ODbL 4.3, which needs a notice of the source, given in THIRD_PARTY.md. https://github.com/gveres/donateacry-corpus
  - Its weak points: the tags are one parent's guess with no second rater, 84% of the clips are hungry, and many installs gave one clip only.
- **Baby Chillanto.** INAOE and CONACYT, Mexico. About 2,268 clips labeled by doctors as normal, hunger, pain, deaf and asphyxia. Access by request, no public terms found. Papers that used it thank INAOE for the data, for example https://arxiv.org/abs/2102.02909 . Not usable without a request, and half its classes are medical.
- **CryCeleb 2023.** Ubenwa, about 26,000 cry segments from 786 newborns at birth and discharge, for telling babies apart. No reason labels. CC BY-NC-ND 4.0 and gated. https://huggingface.co/datasets/Ubenwa/CryCeleb2023 , paper https://arxiv.org/abs/2305.00969
- **Self-supervised infant cry models.** Ubenwa's study of wav2vec 2.0 style pretraining on cries (https://arxiv.org/abs/2305.01578) is about asphyxia and other medical tasks, not everyday reasons.
- **Hugging Face models.** A search for "baby cry" and "infant cry" on Oct 30 2026 found about 20 models. The most downloaded, AmeerHesham/distilhubert-finetuned-baby_cry (Apache 2.0), is fine tuned on a Donate-a-Cry copy. foduucom/baby-cry-classification reports 0.38 accuracy on its card. None reports a test on babies or phones held out from training, and the always-hungry baseline on Donate-a-Cry is already about 0.8 plain accuracy, so their numbers say little. https://huggingface.co/AmeerHesham/distilhubert-finetuned-baby_cry , https://huggingface.co/foduucom/baby-cry-classification
- **Meta audio models.** Meta's Perception Encoder Audio-Visual (PE-AV) embeds audio, video and text and drives SAM Audio, code in https://github.com/facebookresearch/perception_models . Neither has a cry reason head. PE-AV embeddings could replace PANNs as the input to the same head later, which is a measured experiment for another night (SAM-class models were off for this item, and the input is not the bottleneck: the labels are).

## What we built

Details in docs/house-sounds.md and results/cry-reason/README.md.

1. The held-out split and the rule for when the sound may be said were committed in their own commit before the training code existed (results/cry-reason/split.json).
2. PANNs CNN14, already on the Mac to hear "a baby is crying", gives a 2048 number embedding of the cry. A softmax head of 5 x 2048 weights, trained in numpy on the train split, reads it. Every clip goes through the camera's 8 kHz A-law channel first, as at home.
3. The guess is one more signal next to the log. It is said only for classes that cleared the bar on the held-out test. The belly pain tag can only ever become "check on him now", plus the fixed call-the-doctor line when the log holds a red flag.
4. Result: balanced accuracy 0.19 on the held-out test (95% interval 0.16 to 0.29), chance 0.20. The bar was not met, so no class is said. The model runs on every cry and its guess is a `cry_sound_guess` event in the log.

## What would make the sound worth saying

- Labels a second person agreed on, like ChatterBaby's, and more than a handful of babies per class. The cleanest route is our own: once Theo is born, every cry the agent hears is followed by what the log shows next (fed, changed, asleep). Those are labels from what happened, not a guess, and they never leave the house.
- Asking UCLA for research access to ChatterBaby's data, under their terms, for local training only. Not done: it needs Gonza, and their consent forms may not allow it.
