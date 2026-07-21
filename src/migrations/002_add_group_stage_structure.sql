PRAGMA foreign_keys = ON;

CREATE TABLE tournament_draft_groups (
    group_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL,
    group_number INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (draft_id, group_number),
    UNIQUE (draft_id, group_name),

    FOREIGN KEY (draft_id)
        REFERENCES tournament_drafts(draft_id)
        ON DELETE CASCADE
);

CREATE TABLE tournament_draft_group_members (
    group_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    group_position INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (group_id, player_id),

    FOREIGN KEY (group_id)
        REFERENCES tournament_draft_groups(group_id)
        ON DELETE CASCADE,

    FOREIGN KEY (player_id)
        REFERENCES players(player_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_draft_groups_draft
ON tournament_draft_groups(draft_id);

CREATE INDEX idx_draft_group_members_group
ON tournament_draft_group_members(group_id);

CREATE TRIGGER prevent_duplicate_draft_group_member
BEFORE INSERT ON tournament_draft_group_members
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM tournament_draft_group_members AS existing_member
    JOIN tournament_draft_groups AS existing_group
      ON existing_group.group_id = existing_member.group_id
    JOIN tournament_draft_groups AS new_group
      ON new_group.group_id = NEW.group_id
    WHERE existing_member.player_id = NEW.player_id
      AND existing_group.draft_id = new_group.draft_id
)
BEGIN
    SELECT RAISE(
        ABORT,
        'Player is already assigned to another group in this draft.'
    );
END;