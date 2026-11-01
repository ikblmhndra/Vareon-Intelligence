-- View kompatibilitas P7c-1 (spec 3.6): nama tabel lama kini view di atas entity_mentions/
-- entity_watches/entity_profiles/entities, dengan kolom lama, supaya kode 0.8.2/0.8.10 yang
-- di-rollback (deploy.sh tidak pernah menurunkan DB) tetap membaca dan menulis. Dijalankan
-- sesudah tabel lama di-rename jadi _legacy_<nama>.
--
-- Aturan tulis (sama dengan backfill.sql, supaya kode lama menghasilkan baris yang sama):
-- * nama -> entity_resolve(); teknik lewat id teknik (Ruling 7); negara lewat kode ISO
--   (external_id); label industri lewat alias sektor ("General" = tidak ada apa-apa).
-- * id view = entity_mentions.id (atau entity_watches/entity_profiles/entities), diisi trigger
--   INSERT supaya ORM lama dapat RETURNING id; kolom server_default lama juga diisi.
-- * Nama kosong, "General", atau entitas suppressed: tidak ada baris (juga untuk view TA), tidak ada error (Review
--   Focus 5). ORM lama tetap butuh id, jadi trigger memberi id "fantom" dari sekuens
--   entity_mentions; DELETE id fantom tidak melakukan apa-apa.
-- * Bentrok di kunci unik mention (dua ejaan -> satu entitas): baris yang ada diberi id baru dan
--   id itu yang dikembalikan. Alasannya _reconcile 0.8.10: UoW menjalankan INSERT ejaan baru
--   sebelum DELETE baris lama (yang dibaca dengan nama entitas); tanpa ganti id, DELETE itu
--   menghapus mention yang baru saja "ditulis ulang".
-- * UPDATE hanya pada view yang memang di-UPDATE kode lama (article_ttps, article_malware,
--   article_industries: _apply_enrichment/apply_ttps; ta_profiles: save_profile;
--   article_threat_actors, ta_watchlist: perintah canonicalise_actors). Ganti nama = resolve
--   ulang entitas; bentrok di kunci unik tetap error, seperti constraint unik lama.
-- Kunci tidak memakai titik dua diikuti huruf: op.execute() membungkus file ini dalam text().

CREATE FUNCTION entity_compat_method(p_source text, p_default text) RETURNS text
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT CASE WHEN coalesce(p_source, p_default)
                     IN ('dictionary', 'llm', 'keyword', 'explicit', 'analyst')
                THEN coalesce(p_source, p_default) ELSE 'legacy' END
$fn$;

CREATE FUNCTION entity_compat_resolve(p_type text, p_name text) RETURNS bigint
LANGUAGE sql AS $fn$
    SELECT CASE WHEN entity_alias_norm(coalesce(p_name, '')) <> ''
                THEN entity_resolve(p_type, p_name, 'legacy') END
$fn$;

CREATE FUNCTION entity_compat_technique(p_ext_id text, p_name text) RETURNS bigint
LANGUAGE sql AS $fn$
    SELECT CASE WHEN entity_alias_norm(coalesce(p_ext_id, '')) <> ''
                THEN entity_resolve_technique(p_ext_id, p_name, 'legacy') END
$fn$;

-- CVE baru: name = external_id = id CVE huruf besar, source 'cve' (seperti backfill dan
-- cve_mention Python). external_id yang sudah dipegang entitas hidup lain (analis membuat
-- "Log4Shell" ber-external_id CVE itu) tidak diisi ulang: unik (type, external_id) akan gagal.
CREATE FUNCTION entity_compat_cve(p_cve text) RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE
    v_id bigint := entity_compat_resolve('vulnerability', upper(p_cve));
BEGIN
    UPDATE entities e SET external_id = e.name, source = 'cve'
     WHERE e.id = v_id AND e.external_id IS NULL
       AND NOT EXISTS (SELECT 1 FROM entities o
                        WHERE o.type = 'vulnerability' AND o.external_id = e.name
                          AND o.merged_into_id IS NULL);
    RETURN v_id;
END $fn$;

-- label industri -> sektor lewat alias; label tak dikenal -> sektor legacy (identity_class 'class')
CREATE FUNCTION entity_compat_sector(p_label text) RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE
    v_id bigint;
BEGIN
    IF entity_alias_norm(coalesce(p_label, '')) IN ('', 'general') THEN
        RETURN NULL;
    END IF;
    v_id := entity_resolve('identity', p_label, 'legacy');
    UPDATE entities SET identity_class = 'class' WHERE id = v_id AND identity_class IS NULL;
    RETURN v_id;
END $fn$;

-- kode negara -> lokasi lewat external_id; kode tak dikenal -> lokasi legacy (nama = kode)
CREATE FUNCTION entity_compat_country(p_code text) RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE
    v_code text := upper(btrim(coalesce(p_code, '')));
    v_id bigint;
BEGIN
    IF v_code = '' THEN
        RETURN NULL;
    END IF;
    SELECT id INTO v_id FROM entities
     WHERE type = 'location' AND external_id = v_code AND merged_into_id IS NULL;
    IF v_id IS NULL THEN
        INSERT INTO entities (type, stix_id, name, external_id, source)
        VALUES ('location', 'location--' || gen_random_uuid(), v_code, v_code, 'legacy')
        ON CONFLICT DO NOTHING;
        -- kode baru yang namanya bentrok dengan lokasi lain (unik type+lower(name)) tidak dibuat:
        -- v_id tetap NULL -> mention fantom, sengaja (sama dengan backfill yang melewatinya)
        SELECT id INTO v_id FROM entities
         WHERE type = 'location' AND external_id = v_code AND merged_into_id IS NULL;
        INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
        SELECT v_id, 'location', v_code, entity_alias_norm(v_code), 'legacy' WHERE v_id IS NOT NULL
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN v_id;
END $fn$;

-- satu mention; mengembalikan id untuk view (lihat aturan id fantom dan ganti id di atas)
CREATE FUNCTION entity_compat_mention(p_entity bigint, p_article bigint, p_indicator bigint,
                                      p_cve bigint, p_method text, p_alias text,
                                      p_role text DEFAULT NULL, p_evidence text DEFAULT NULL,
                                      p_extracted jsonb DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql AS $fn$
DECLARE
    v_id bigint;
BEGIN
    IF p_entity IS NULL OR (SELECT suppressed FROM entities WHERE id = p_entity) THEN
        RETURN nextval('entity_mentions_id_seq');
    END IF;
    INSERT INTO entity_mentions (article_id, indicator_id, cve_tracker_id, entity_id, method,
                                 matched_alias, role, evidence, extracted)
    VALUES (p_article, p_indicator, p_cve, p_entity, p_method, p_alias, p_role, p_evidence,
            p_extracted)
    ON CONFLICT DO NOTHING
    RETURNING id INTO v_id;
    IF v_id IS NULL THEN
        UPDATE entity_mentions SET id = nextval('entity_mentions_id_seq')
         WHERE entity_id = p_entity AND article_id IS NOT DISTINCT FROM p_article
           AND indicator_id IS NOT DISTINCT FROM p_indicator
           AND cve_tracker_id IS NOT DISTINCT FROM p_cve AND role IS NOT DISTINCT FROM p_role
        RETURNING id INTO v_id;
    END IF;
    RETURN coalesce(v_id, nextval('entity_mentions_id_seq'));
END $fn$;

-- UPDATE yang mengganti kunci: arahkan mention ke entitas baru; NULL (kosong, "General") atau
-- suppressed -> mention dihapus, sama dengan INSERT yang dibuang
CREATE FUNCTION entity_compat_repoint(p_id bigint, p_entity bigint, p_alias text)
RETURNS void LANGUAGE plpgsql AS $fn$
BEGIN
    IF p_entity IS NULL OR (SELECT suppressed FROM entities WHERE id = p_entity) THEN
        DELETE FROM entity_mentions WHERE id = p_id;
    ELSE
        UPDATE entity_mentions SET entity_id = p_entity, matched_alias = p_alias WHERE id = p_id;
    END IF;
END $fn$;

CREATE FUNCTION entity_compat_extracted(p_id text, p_name text) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $fn$
    SELECT nullif(jsonb_strip_nulls(jsonb_build_object('extracted_id', p_id,
                                                       'extracted_name', p_name)), '{}'::jsonb)
$fn$;

-- ---------------------------------------------------------------------------------------------
-- article_threat_actors(id, article_id, threat_actor, source)
CREATE VIEW article_threat_actors AS
SELECT m.id, m.article_id, e.name AS threat_actor, m.method AS source
  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
 WHERE e.type = 'intrusion-set' AND m.article_id IS NOT NULL;

CREATE FUNCTION article_threat_actors_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_mentions WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    NEW.source := entity_compat_method(NEW.source, 'dictionary');
    IF TG_OP = 'INSERT' THEN
        NEW.id := entity_compat_mention(entity_compat_resolve('intrusion-set', NEW.threat_actor),
                                        NEW.article_id, NULL, NULL, NEW.source, NEW.threat_actor);
        RETURN NEW;
    END IF;
    IF NEW.threat_actor IS DISTINCT FROM OLD.threat_actor THEN
        PERFORM entity_compat_repoint(
            OLD.id, entity_compat_resolve('intrusion-set', NEW.threat_actor), NEW.threat_actor);
    END IF;
    UPDATE entity_mentions SET method = NEW.source WHERE id = OLD.id;
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_article_threat_actors_compat INSTEAD OF INSERT OR UPDATE OR DELETE
    ON article_threat_actors FOR EACH ROW EXECUTE FUNCTION article_threat_actors_compat();

-- article_malware(id, article_id, name, kind, source)
CREATE VIEW article_malware AS
SELECT m.id, m.article_id, e.name, e.type AS kind, m.method AS source
  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
 WHERE e.type IN ('malware', 'tool') AND m.article_id IS NOT NULL;

CREATE FUNCTION article_malware_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_mentions WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    NEW.source := entity_compat_method(NEW.source, 'dictionary');
    IF TG_OP = 'INSERT' THEN
        NEW.id := entity_compat_mention(
            entity_compat_resolve(CASE WHEN NEW.kind = 'tool' THEN 'tool' ELSE 'malware' END,
                                  NEW.name),
            NEW.article_id, NULL, NULL, NEW.source, NEW.name);
        RETURN NEW;
    END IF;
    IF (NEW.name, NEW.kind) IS DISTINCT FROM (OLD.name, OLD.kind) THEN
        PERFORM entity_compat_repoint(
            OLD.id,
            entity_compat_resolve(CASE WHEN NEW.kind = 'tool' THEN 'tool' ELSE 'malware' END,
                                  NEW.name),
            NEW.name);
    END IF;
    UPDATE entity_mentions SET method = NEW.source WHERE id = OLD.id;
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_article_malware_compat INSTEAD OF INSERT OR UPDATE OR DELETE
    ON article_malware FOR EACH ROW EXECUTE FUNCTION article_malware_compat();

-- article_ttps(id, article_id, ttp_id, ttp_name, extracted_id, extracted_name, source, evidence)
-- ttp_name = nama entitas; perubahan ttp_name dari kode lama diabaikan (identitas = id teknik)
CREATE VIEW article_ttps AS
SELECT m.id, m.article_id, e.external_id AS ttp_id, e.name AS ttp_name,
       m.extracted ->> 'extracted_id' AS extracted_id,
       m.extracted ->> 'extracted_name' AS extracted_name, m.method AS source, m.evidence
  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
 WHERE e.type = 'attack-pattern' AND m.article_id IS NOT NULL;

CREATE FUNCTION article_ttps_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_mentions WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    NEW.source := entity_compat_method(NEW.source, 'llm');
    IF TG_OP = 'INSERT' THEN
        NEW.id := entity_compat_mention(
            entity_compat_technique(NEW.ttp_id, NEW.ttp_name), NEW.article_id, NULL, NULL,
            NEW.source, NEW.ttp_id, NULL, NEW.evidence,
            entity_compat_extracted(NEW.extracted_id, NEW.extracted_name));
        RETURN NEW;
    END IF;
    IF NEW.ttp_id IS DISTINCT FROM OLD.ttp_id THEN
        PERFORM entity_compat_repoint(
            OLD.id, entity_compat_technique(NEW.ttp_id, NEW.ttp_name), NEW.ttp_id);
    END IF;
    UPDATE entity_mentions
       SET method = NEW.source, evidence = NEW.evidence,
           extracted = entity_compat_extracted(NEW.extracted_id, NEW.extracted_name)
     WHERE id = OLD.id;
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_article_ttps_compat INSTEAD OF INSERT OR UPDATE OR DELETE
    ON article_ttps FOR EACH ROW EXECUTE FUNCTION article_ttps_compat();

-- article_cves(article_id, cve_id, in_title, first_seen_at); kunci lama = (article_id, cve_id)
CREATE VIEW article_cves AS
SELECT m.article_id, e.name AS cve_id,
       coalesce((m.extracted ->> 'in_title')::boolean, false) AS in_title,
       coalesce((m.extracted ->> 'first_seen_at')::timestamptz, m.created_at) AS first_seen_at
  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
 WHERE e.type = 'vulnerability' AND m.article_id IS NOT NULL;

CREATE FUNCTION article_cves_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_mentions m USING entities e
         WHERE m.article_id = OLD.article_id AND e.id = m.entity_id
           AND e.type = 'vulnerability' AND e.name = OLD.cve_id;
        RETURN OLD;
    END IF;
    NEW.in_title := coalesce(NEW.in_title, false);
    NEW.first_seen_at := coalesce(NEW.first_seen_at, now());
    PERFORM entity_compat_mention(
        entity_compat_cve(NEW.cve_id), NEW.article_id, NULL, NULL, 'legacy', NEW.cve_id, NULL,
        NULL, jsonb_build_object('in_title', NEW.in_title, 'first_seen_at', NEW.first_seen_at));
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_article_cves_compat INSTEAD OF INSERT OR DELETE
    ON article_cves FOR EACH ROW EXECUTE FUNCTION article_cves_compat();

-- article_countries(id, article_id, country_code, role)
CREATE VIEW article_countries AS
SELECT m.id, m.article_id, e.external_id AS country_code, m.role
  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
 WHERE e.type = 'location' AND m.article_id IS NOT NULL;

CREATE FUNCTION article_countries_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_mentions WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    NEW.id := entity_compat_mention(entity_compat_country(NEW.country_code), NEW.article_id,
                                    NULL, NULL, 'legacy', NEW.country_code, NEW.role);
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_article_countries_compat INSTEAD OF INSERT OR DELETE
    ON article_countries FOR EACH ROW EXECUTE FUNCTION article_countries_compat();

-- article_industries(id, article_id, industry, source); industry = label asli (matched_alias)
CREATE VIEW article_industries AS
SELECT m.id, m.article_id, m.matched_alias AS industry, m.method AS source
  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
 WHERE e.type = 'identity' AND e.identity_class = 'class' AND m.article_id IS NOT NULL;

CREATE FUNCTION article_industries_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_mentions WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    NEW.source := entity_compat_method(NEW.source, 'llm');
    IF TG_OP = 'INSERT' THEN
        NEW.id := entity_compat_mention(entity_compat_sector(NEW.industry), NEW.article_id,
                                        NULL, NULL, NEW.source, NEW.industry);
        RETURN NEW;
    END IF;
    IF NEW.industry IS DISTINCT FROM OLD.industry THEN
        PERFORM entity_compat_repoint(OLD.id, entity_compat_sector(NEW.industry), NEW.industry);
    END IF;
    UPDATE entity_mentions SET method = NEW.source WHERE id = OLD.id;
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_article_industries_compat INSTEAD OF INSERT OR UPDATE OR DELETE
    ON article_industries FOR EACH ROW EXECUTE FUNCTION article_industries_compat();

-- indicator_threat_actors(id, indicator_id, threat_actor): ditulis 0.8.10 lewat view P7a
-- ioc_threat_actors (IOC API) dan dihapus lewat cascade ORM saat IOC dihapus
CREATE VIEW indicator_threat_actors AS
SELECT m.id, m.indicator_id, e.name AS threat_actor
  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
 WHERE e.type = 'intrusion-set' AND m.indicator_id IS NOT NULL;

CREATE FUNCTION indicator_threat_actors_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_mentions WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    NEW.id := entity_compat_mention(entity_compat_resolve('intrusion-set', NEW.threat_actor),
                                    NULL, NEW.indicator_id, NULL, 'legacy', NEW.threat_actor);
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_indicator_threat_actors_compat INSTEAD OF INSERT OR DELETE
    ON indicator_threat_actors FOR EACH ROW EXECUTE FUNCTION indicator_threat_actors_compat();

-- cve_threat_actors(id, cve_tracker_id, threat_actor) / cve_ttps(id, cve_tracker_id, ttp_id,
-- ttp_name): dihapus lewat cascade ORM saat CVE tracker dihapus
CREATE VIEW cve_threat_actors AS
SELECT m.id, m.cve_tracker_id, e.name AS threat_actor
  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
 WHERE e.type = 'intrusion-set' AND m.cve_tracker_id IS NOT NULL;

CREATE FUNCTION cve_threat_actors_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_mentions WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    NEW.id := entity_compat_mention(entity_compat_resolve('intrusion-set', NEW.threat_actor),
                                    NULL, NULL, NEW.cve_tracker_id, 'legacy', NEW.threat_actor);
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_cve_threat_actors_compat INSTEAD OF INSERT OR DELETE
    ON cve_threat_actors FOR EACH ROW EXECUTE FUNCTION cve_threat_actors_compat();

CREATE VIEW cve_ttps AS
SELECT m.id, m.cve_tracker_id, e.external_id AS ttp_id, e.name AS ttp_name
  FROM entity_mentions m JOIN entities e ON e.id = m.entity_id
 WHERE e.type = 'attack-pattern' AND m.cve_tracker_id IS NOT NULL;

CREATE FUNCTION cve_ttps_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_mentions WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    NEW.id := entity_compat_mention(entity_compat_technique(NEW.ttp_id, NEW.ttp_name), NULL,
                                    NULL, NEW.cve_tracker_id, 'legacy', NEW.ttp_id);
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_cve_ttps_compat INSTEAD OF INSERT OR DELETE
    ON cve_ttps FOR EACH ROW EXECUTE FUNCTION cve_ttps_compat();

-- ---------------------------------------------------------------------------------------------
-- ta_watchlist(id, name, client_id, created_at, updated_at)
CREATE VIEW ta_watchlist AS
SELECT w.id, e.name, w.client_id, w.created_at, w.created_at AS updated_at
  FROM entity_watches w JOIN entities e ON e.id = w.entity_id
 WHERE e.type = 'intrusion-set';

CREATE FUNCTION ta_watchlist_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE
    v_entity bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_watches WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    v_entity := entity_compat_resolve('intrusion-set', NEW.name);
    IF v_entity IS NULL THEN  -- nama kosong: id fantom, tanpa baris, tanpa error
        IF TG_OP = 'INSERT' THEN
            NEW.id := nextval('entity_watches_id_seq');
            NEW.created_at := now();
            NEW.updated_at := NEW.created_at;
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        UPDATE entity_watches SET entity_id = v_entity, client_id = NEW.client_id
         WHERE id = OLD.id;
        RETURN NEW;
    END IF;
    INSERT INTO entity_watches (client_id, entity_id) VALUES (NEW.client_id, v_entity)
    ON CONFLICT DO NOTHING;
    SELECT id, created_at, created_at INTO NEW.id, NEW.created_at, NEW.updated_at
      FROM entity_watches WHERE client_id = NEW.client_id AND entity_id = v_entity;
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_ta_watchlist_compat INSTEAD OF INSERT OR UPDATE OR DELETE
    ON ta_watchlist FOR EACH ROW EXECUTE FUNCTION ta_watchlist_compat();

-- ta_profiles(id, actor_name, profile, generated_at); INSERT = upsert per aktor
CREATE VIEW ta_profiles AS
SELECT p.id, e.name AS actor_name, coalesce(p.profile, '{}'::jsonb) AS profile, p.generated_at
  FROM entity_profiles p JOIN entities e ON e.id = p.entity_id
 WHERE e.type = 'intrusion-set';

CREATE FUNCTION ta_profiles_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE
    v_entity bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM entity_profiles WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    NEW.profile := coalesce(NEW.profile, '{}'::jsonb);
    NEW.generated_at := coalesce(NEW.generated_at, now());
    IF TG_OP = 'UPDATE' THEN
        IF entity_alias_norm(NEW.actor_name) IS DISTINCT FROM entity_alias_norm(OLD.actor_name) THEN
            v_entity := entity_compat_resolve('intrusion-set', NEW.actor_name);
        END IF;
        UPDATE entity_profiles
           SET entity_id = coalesce(v_entity, entity_id), profile = NEW.profile,
               generated_at = NEW.generated_at
         WHERE id = OLD.id;
        RETURN NEW;
    END IF;
    v_entity := entity_compat_resolve('intrusion-set', NEW.actor_name);
    IF v_entity IS NULL THEN  -- nama kosong: id fantom, tanpa baris, tanpa error
        NEW.id := nextval('entity_profiles_id_seq');
        RETURN NEW;
    END IF;
    INSERT INTO entity_profiles (entity_id, profile, generated_at)
    VALUES (v_entity, NEW.profile, NEW.generated_at)
    ON CONFLICT (entity_id) DO UPDATE
       SET profile = EXCLUDED.profile, generated_at = EXCLUDED.generated_at
    RETURNING id INTO NEW.id;
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_ta_profiles_compat INSTEAD OF INSERT OR UPDATE OR DELETE
    ON ta_profiles FOR EACH ROW EXECUTE FUNCTION ta_profiles_compat();

-- ta_whitelist(id, name, added_date) = aktor suppressed; id = entities.id, nama huruf kecil
-- seperti tabel lama; INSERT = suppress, DELETE = unsuppress
CREATE VIEW ta_whitelist AS
SELECT e.id, lower(e.name) AS name, e.updated_at AS added_date
  FROM entities e
 WHERE e.type = 'intrusion-set' AND e.suppressed AND e.merged_into_id IS NULL;

CREATE FUNCTION ta_whitelist_compat() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE
    v_entity bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        UPDATE entities SET suppressed = false, updated_at = now()
         WHERE id = OLD.id AND suppressed;
        RETURN OLD;
    END IF;
    v_entity := entity_compat_resolve('intrusion-set', NEW.name);
    IF v_entity IS NULL THEN  -- nama kosong: id fantom, tanpa entitas, tanpa error
        NEW.id := nextval('entities_id_seq');
        NEW.added_date := now();
        RETURN NEW;
    END IF;
    UPDATE entities SET suppressed = true, updated_at = now()
     WHERE id = v_entity AND NOT suppressed;
    SELECT id, updated_at INTO NEW.id, NEW.added_date FROM entities WHERE id = v_entity;
    RETURN NEW;
END $fn$;
CREATE TRIGGER trg_ta_whitelist_compat INSTEAD OF INSERT OR DELETE
    ON ta_whitelist FOR EACH ROW EXECUTE FUNCTION ta_whitelist_compat();

-- view P7a ioc_threat_actors dipasang ulang di atas view indicator_threat_actors (sebelumnya
-- menunjuk tabel yang kini _legacy_indicator_threat_actors)
CREATE VIEW ioc_threat_actors AS
SELECT id, indicator_id AS ioc_id, threat_actor FROM indicator_threat_actors;
COMMENT ON VIEW ioc_threat_actors IS
    'deprecated since 0.8.11: compatibility view, writable through the indicator_threat_actors triggers; use indicator_*';
