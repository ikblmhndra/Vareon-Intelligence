-- Kembaran SQL dari cti_core.entity.resolve.resolve(); aturan normalisasi identik dengan
-- cti_core.entity.alias_norm (himpunan spasi eksplisit, file ini sengaja ASCII: chr()).
-- lower() bergantung pada locale DB (en_US.utf8 di postgres:16-alpine, dicek di dev).
CREATE FUNCTION entity_collapse_ws(p_s text) RETURNS text LANGUAGE sql IMMUTABLE AS $fn$
    SELECT btrim(regexp_replace(p_s,
        '[\t\n\v\f\r ' || chr(160) || chr(5760) || chr(8192) || '-' || chr(8203)
        || chr(8232) || chr(8233) || chr(8239) || chr(8287) || chr(12288) || chr(65279) || ']+',
        ' ', 'g'), ' ')
$fn$;

CREATE FUNCTION entity_alias_norm(p_s text) RETURNS text LANGUAGE sql IMMUTABLE AS $fn$
    SELECT lower(entity_collapse_ws(p_s))
$fn$;

-- cari entitas hidup lewat alias, ikuti tombstone merge (maks 20 lompatan)
CREATE FUNCTION entity_resolve_lookup(p_type text, p_norm text) RETURNS bigint
LANGUAGE plpgsql AS $fn$
DECLARE
    v_id bigint;
    v_next bigint;
BEGIN
    SELECT entity_id INTO v_id FROM entity_aliases
     WHERE entity_type = p_type AND alias_norm = p_norm;
    FOR i IN 1..20 LOOP
        IF v_id IS NULL THEN RETURN NULL; END IF;
        SELECT merged_into_id INTO v_next FROM entities WHERE id = v_id;
        IF v_next IS NULL THEN RETURN v_id; END IF;
        v_id := v_next;
    END LOOP;
    RAISE EXCEPTION 'rantai merge terlalu panjang/siklik untuk % %', p_type, p_norm;
END $fn$;

-- stix_id entitas baru = tipe || '--' || gen_random_uuid() (bukan uuid5 seperti Python):
-- stix_id hanya perlu stabil sejak dibuat; keunikan entitas dijaga lewat lookup alias.
CREATE FUNCTION entity_resolve(p_type text, p_name text, p_source text) RETURNS bigint
LANGUAGE plpgsql AS $fn$
DECLARE
    v_name text := entity_collapse_ws(p_name);
    v_norm text := lower(v_name);
    v_id bigint := entity_resolve_lookup(p_type, v_norm);
BEGIN
    IF v_id IS NOT NULL THEN RETURN v_id; END IF;

    INSERT INTO entities (type, stix_id, name, source)
    VALUES (p_type, p_type || '--' || gen_random_uuid(), v_name, p_source)
    ON CONFLICT DO NOTHING
    RETURNING id INTO v_id;
    IF v_id IS NULL THEN  -- nama sudah dipakai entitas hidup tanpa alias ini
        SELECT id INTO v_id FROM entities
         WHERE type = p_type AND lower(name) = v_norm AND merged_into_id IS NULL;
    END IF;
    IF v_id IS NULL THEN
        RAISE EXCEPTION 'entity_resolve gagal membuat/menemukan % %', p_type, p_name;
    END IF;
    INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
    VALUES (v_id, p_type, v_name, v_norm, p_source)
    ON CONFLICT DO NOTHING;

    v_id := entity_resolve_lookup(p_type, v_norm);
    IF v_id IS NULL THEN
        RAISE EXCEPTION 'entity_resolve gagal untuk % %', p_type, p_name;
    END IF;
    RETURN v_id;
END $fn$;
