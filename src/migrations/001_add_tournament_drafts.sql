PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tournament_drafts (
    draft_id TEXT PRIMARY KEY,

    tournament_number INTEGER NOT NULL UNIQUE,
    tournament_date TEXT,

    format_type TEXT NOT NULL
        CHECK (
            format_type IN (
                'group_stage_double_elimination',
                'double_elimination'
            )
        ),

    bracket_entry_mode TEXT NOT NULL
        CHECK (
            bracket_entry_mode IN (
                'all_winners',
                'split_by_group_seed'
            )
        ),

    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (
            status IN (
                'draft',
                'group_stage',
                'bracket_ready',
                'in_progress',
                'completed',
                'cancelled'
            )
        ),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (
        format_type = 'group_stage_double_elimination'
        OR bracket_entry_mode = 'all_winners'
    )
);


CREATE TABLE IF NOT EXISTS tournament_draft_participants (
    draft_id TEXT NOT NULL,
    player_id TEXT NOT NULL,

    manual_seed INTEGER,
    group_seed INTEGER,
    bracket_seed INTEGER,

    starts_in TEXT NOT NULL DEFAULT 'winners'
        CHECK (
            starts_in IN (
                'winners',
                'losers'
            )
        ),

    PRIMARY KEY (
        draft_id,
        player_id
    ),

    UNIQUE (
        draft_id,
        manual_seed
    ),

    UNIQUE (
        draft_id,
        group_seed
    ),

    UNIQUE (
        draft_id,
        bracket_seed
    ),

    FOREIGN KEY (draft_id)
        REFERENCES tournament_drafts(draft_id)
        ON DELETE CASCADE,

    FOREIGN KEY (player_id)
        REFERENCES players(player_id)
        ON DELETE RESTRICT
);