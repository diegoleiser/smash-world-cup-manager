PRAGMA foreign_keys = ON;

CREATE TABLE tournament_draft_group_matches (
    group_match_id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    match_number INTEGER NOT NULL,

    player_1_id TEXT NOT NULL,
    player_2_id TEXT NOT NULL,
    winner_id TEXT,

    player_1_score INTEGER,
    player_2_score INTEGER,

    status TEXT NOT NULL DEFAULT 'pending',
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (group_id, round_number, match_number),

    CHECK (round_number > 0),
    CHECK (match_number > 0),
    CHECK (player_1_id != player_2_id),

    CHECK (
        status IN (
            'pending',
            'completed',
            'forfeit',
            'cancelled'
        )
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
        winner_id IS NULL
        OR winner_id = player_1_id
        OR winner_id = player_2_id
    ),

    CHECK (
        status != 'completed'
        OR (
            winner_id IS NOT NULL
            AND player_1_score IS NOT NULL
            AND player_2_score IS NOT NULL
            AND player_1_score != player_2_score
        )
    ),

    CHECK (
        status != 'forfeit'
        OR (
            winner_id IS NOT NULL
            AND player_1_score IS NULL
            AND player_2_score IS NULL
        )
    ),

    CHECK (
        status NOT IN ('pending', 'cancelled')
        OR (
            winner_id IS NULL
            AND player_1_score IS NULL
            AND player_2_score IS NULL
        )
    ),

    FOREIGN KEY (group_id)
        REFERENCES tournament_draft_groups(group_id)
        ON DELETE CASCADE,

    FOREIGN KEY (group_id, player_1_id)
        REFERENCES tournament_draft_group_members(
            group_id,
            player_id
        )
        ON DELETE CASCADE,

    FOREIGN KEY (group_id, player_2_id)
        REFERENCES tournament_draft_group_members(
            group_id,
            player_id
        )
        ON DELETE CASCADE
);

CREATE INDEX idx_draft_group_matches_group
ON tournament_draft_group_matches(group_id);

CREATE INDEX idx_draft_group_matches_status
ON tournament_draft_group_matches(status);

CREATE TRIGGER prevent_duplicate_group_match
BEFORE INSERT ON tournament_draft_group_matches
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM tournament_draft_group_matches AS existing_match
    WHERE existing_match.group_id = NEW.group_id
      AND (
          (
              existing_match.player_1_id = NEW.player_1_id
              AND existing_match.player_2_id = NEW.player_2_id
          )
          OR
          (
              existing_match.player_1_id = NEW.player_2_id
              AND existing_match.player_2_id = NEW.player_1_id
          )
      )
)
BEGIN
    SELECT RAISE(
        ABORT,
        'A group match between these players already exists.'
    );
END;