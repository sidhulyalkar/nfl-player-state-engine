# Optional LLM public-context extraction prompt

Use only the supplied public, player-authored documents. Return JSON that conforms to the repository's `PersonaSnapshot` schema.

The output is a weak sports-context hypothesis, not a psychological profile. Extract only observable football-relevant signals:

- training or film-study emphasis
- recovery or return-to-play discussion
- competitive language
- team-oriented language
- leadership language
- explicit matchup discussion
- explicit role or workload expectations
- commercial-content share

For each non-zero signal, cite document IDs and short excerpts. Never infer race, ethnicity, religion, sexuality, political affiliation, diagnoses, substance use, financial status, or private family information. Do not convert jokes, advertisements, lyrics, reposts, or fan comments into player beliefs. Use zero and low confidence when evidence is sparse.
