-- Jam feed TAXII/REST (spec 3.5), pola `trg_indicators_feed_bump` P7b: `clock_timestamp()` dan
-- IS DISTINCT FROM per kolom. Dipasang SESUDAH backfill supaya muatan massal tidak menggeser jam.
-- first_seen/last_seen/updated_at sengaja tidak memicu bump (berubah tiap artikel, tak diterbitkan).
-- Trigger mention juga menyala untuk view kompatibilitas (INSERT/DELETE view menulis
-- entity_mentions), jadi kode lama hasil rollback tetap menggeser jam story: disengaja.

CREATE FUNCTION entities_feed_bump() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.name IS DISTINCT FROM OLD.name
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.external_id IS DISTINCT FROM OLD.external_id
       OR NEW.suppressed IS DISTINCT FROM OLD.suppressed
       OR NEW.merged_into_id IS DISTINCT FROM OLD.merged_into_id
       OR NEW.tlp IS DISTINCT FROM OLD.tlp
       OR NEW.identity_class IS DISTINCT FROM OLD.identity_class
    THEN
        NEW.feed_changed_at = clock_timestamp();
    END IF;
    RETURN NEW;
END $fn$;

CREATE TRIGGER trg_entities_feed_bump BEFORE UPDATE ON entities
FOR EACH ROW EXECUTE FUNCTION entities_feed_bump();

-- merge/split memindah alias lewat UPDATE entity_id: entitas lama DAN baru bump (OLD/NEW NULL
-- pada INSERT/DELETE, jadi IN (...) cukup untuk ketiga operasi)
CREATE FUNCTION entity_aliases_feed_bump() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    UPDATE entities SET feed_changed_at = clock_timestamp()
    WHERE id IN (OLD.entity_id, NEW.entity_id);
    RETURN NULL;
END $fn$;

CREATE TRIGGER trg_entity_aliases_feed_bump
AFTER INSERT OR DELETE OR UPDATE OF alias, entity_id ON entity_aliases
FOR EACH ROW EXECUTE FUNCTION entity_aliases_feed_bump();

CREATE FUNCTION relationships_feed_bump() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.relationship_type IS DISTINCT FROM OLD.relationship_type
       OR NEW.source_entity_id IS DISTINCT FROM OLD.source_entity_id
       OR NEW.source_indicator_id IS DISTINCT FROM OLD.source_indicator_id
       OR NEW.target_entity_id IS DISTINCT FROM OLD.target_entity_id
       OR NEW.confidence IS DISTINCT FROM OLD.confidence
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
       OR NEW.tlp IS DISTINCT FROM OLD.tlp
    THEN
        NEW.feed_changed_at = clock_timestamp();
    END IF;
    RETURN NEW;
END $fn$;

CREATE TRIGGER trg_relationships_feed_bump BEFORE UPDATE ON relationships
FOR EACH ROW EXECUTE FUNCTION relationships_feed_bump();

CREATE FUNCTION stories_feed_bump() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF NEW.title IS DISTINCT FROM OLD.title
       OR NEW.article_count IS DISTINCT FROM OLD.article_count
    THEN
        NEW.feed_changed_at = clock_timestamp();
    END IF;
    RETURN NEW;
END $fn$;

CREATE TRIGGER trg_stories_feed_bump BEFORE UPDATE ON stories
FOR EACH ROW EXECUTE FUNCTION stories_feed_bump();

-- object_refs story berubah saat mention artikelnya berubah; mention tanpa artikel/story dilewati.
-- UPDATE (merge/split memindah entity_id, atau article_id pindah) membump story lama DAN baru.
CREATE FUNCTION entity_mentions_feed_bump() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    UPDATE stories SET feed_changed_at = clock_timestamp()
    WHERE id IN (SELECT story_id FROM articles WHERE id IN (OLD.article_id, NEW.article_id));
    RETURN NULL;
END $fn$;

CREATE TRIGGER trg_entity_mentions_feed_bump
AFTER INSERT OR DELETE OR UPDATE OF entity_id, article_id ON entity_mentions
FOR EACH ROW EXECUTE FUNCTION entity_mentions_feed_bump();

-- Propagasi jam (Ruling 33, spec R7): visibilitas relasi dan `object_refs` report bergantung pada
-- suppressed/merge/TLP entitas ujung atau entitas yang disebut. Tanpa bump, konsumen inkremental
-- menyimpan relasi yang kini tersembunyi dan report dengan ref basi. AFTER (bukan di BEFORE
-- entities_feed_bump) karena menulis tabel lain; WHEN menyaring UPDATE yang tidak mengubah apa pun.
CREATE FUNCTION entities_feed_propagate() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    UPDATE relationships SET feed_changed_at = clock_timestamp()
    WHERE source_entity_id = NEW.id OR target_entity_id = NEW.id;
    UPDATE stories SET feed_changed_at = clock_timestamp()
    WHERE id IN (
        SELECT a.story_id FROM entity_mentions m JOIN articles a ON a.id = m.article_id
        WHERE m.entity_id = NEW.id AND a.story_id IS NOT NULL
    );
    RETURN NULL;
END $fn$;

CREATE TRIGGER trg_entities_feed_propagate
AFTER UPDATE OF suppressed, merged_into_id, tlp ON entities
FOR EACH ROW
WHEN (OLD.suppressed IS DISTINCT FROM NEW.suppressed
      OR OLD.merged_into_id IS DISTINCT FROM NEW.merged_into_id
      OR OLD.tlp IS DISTINCT FROM NEW.tlp)
EXECUTE FUNCTION entities_feed_propagate();

-- Indikator artikel ikut `object_refs` report: sumber indikator masuk/keluar/pindah artikel
-- membump story lama DAN baru (pola entity_mentions_feed_bump).
CREATE FUNCTION indicator_sources_feed_bump() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    UPDATE stories SET feed_changed_at = clock_timestamp()
    WHERE id IN (SELECT story_id FROM articles WHERE id IN (OLD.article_id, NEW.article_id));
    RETURN NULL;
END $fn$;

CREATE TRIGGER trg_indicator_sources_feed_bump
AFTER INSERT OR DELETE OR UPDATE OF article_id ON indicator_sources
FOR EACH ROW EXECUTE FUNCTION indicator_sources_feed_bump();
