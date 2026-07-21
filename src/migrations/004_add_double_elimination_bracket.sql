PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tournament_draft_bracket_seeds (
    draft_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    bracket_seed INTEGER NOT NULL,
    starts_in TEXT NOT NULL,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (draft_id, player_id),

    FOREIGN KEY (draft_id)
        REFERENCES tournament_drafts(draft_id)
        ON DELETE CASCADE,

    FOREIGN KEY (player_id)
        REFERENCES players(player_id)
        ON DELETE RESTRICT,

    CHECK (bracket_seed > 0),

    CHECK (
        starts_in IN (
            'winners',
            'losers'
        )
    ),

    UNIQUE (draft_id, bracket_seed)
);


CREATE TABLE IF NOT EXISTS tournament_draft_bracket_matches (
    bracket_match_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL,

    match_code TEXT NOT NULL,
    bracket_side TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    match_number INTEGER NOT NULL,
    round_label TEXT NOT NULL,
    match_type TEXT NOT NULL DEFAULT 'standard',

    player_1_id TEXT,
    player_2_id TEXT,
    winner_id TEXT,

    player_1_score INTEGER,
    player_2_score INTEGER,

    status TEXT NOT NULL DEFAULT 'waiting',

    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (draft_id)
        REFERENCES tournament_drafts(draft_id)
        ON DELETE CASCADE,

    FOREIGN KEY (player_1_id)
        REFERENCES players(player_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (player_2_id)
        REFERENCES players(player_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (winner_id)
        REFERENCES players(player_id)
        ON DELETE RESTRICT,

    CHECK (round_number > 0),
    CHECK (match_number > 0),

    CHECK (
        bracket_side IN (
            'winners',
            'losers',
            'finals'
        )
    ),

    CHECK (
        match_type IN (
            'standard',
            'winners_final',
            'losers_final',
            'grand_final',
            'grand_final_reset'
        )
    ),

    CHECK (
        status IN (
            'inactive',
            'waiting',
            'pending',
            'completed',
            'forfeit',
            'bye',
            'cancelled'
        )
    ),

    CHECK (
        player_1_id IS NULL
        OR player_2_id IS NULL
        OR player_1_id != player_2_id
    ),

    CHECK (
        winner_id IS NULL
        OR winner_id = player_1_id
        OR winner_id = player_2_id
    ),

    CHECK (
        player_1_score IS NULL
        OR player_1_score >= 0
    ),

    CHECK (
        player_2_score IS NULL
        OR player_2_score >= 0
    ),

    CHECK (
        (
            status = 'completed'
            AND player_1_id IS NOT NULL
            AND player_2_id IS NOT NULL
            AND winner_id IS NOT NULL
            AND player_1_score IS NOT NULL
            AND player_2_score IS NOT NULL
            AND player_1_score != player_2_score
        )
        OR status != 'completed'
    ),

    CHECK (
        (
            status IN ('forfeit', 'bye')
            AND winner_id IS NOT NULL
            AND player_1_score IS NULL
            AND player_2_score IS NULL
        )
        OR status NOT IN ('forfeit', 'bye')
    ),

    UNIQUE (draft_id, match_code),

    UNIQUE (
        draft_id,
        bracket_side,
        round_number,
        match_number
    )
);


CREATE TABLE IF NOT EXISTS tournament_draft_bracket_routes (
    route_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL,

    source_match_id TEXT NOT NULL,
    source_outcome TEXT NOT NULL,

    target_match_id TEXT NOT NULL,
    target_slot INTEGER NOT NULL,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (draft_id)
        REFERENCES tournament_drafts(draft_id)
        ON DELETE CASCADE,

    FOREIGN KEY (source_match_id)
        REFERENCES tournament_draft_bracket_matches(bracket_match_id)
        ON DELETE CASCADE,

    FOREIGN KEY (target_match_id)
        REFERENCES tournament_draft_bracket_matches(bracket_match_id)
        ON DELETE CASCADE,

    CHECK (
        source_outcome IN (
            'winner',
            'loser'
        )
    ),

    CHECK (
        target_slot IN (1, 2)
    ),

    CHECK (
        source_match_id != target_match_id
    ),

    UNIQUE (
        source_match_id,
        source_outcome
    ),

    UNIQUE (
        target_match_id,
        target_slot
    )
);


CREATE INDEX IF NOT EXISTS
idx_draft_bracket_seeds_draft
ON tournament_draft_bracket_seeds (
    draft_id,
    bracket_seed
);


CREATE INDEX IF NOT EXISTS
idx_draft_bracket_matches_draft
ON tournament_draft_bracket_matches (
    draft_id,
    bracket_side,
    round_number,
    match_number
);


CREATE INDEX IF NOT EXISTS
idx_draft_bracket_routes_source
ON tournament_draft_bracket_routes (
    source_match_id,
    source_outcome
);


CREATE INDEX IF NOT EXISTS
idx_draft_bracket_routes_target
ON tournament_draft_bracket_routes (
    target_match_id,
    target_slot
);