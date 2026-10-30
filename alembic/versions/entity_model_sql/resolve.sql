-- Kembaran SQL dari cti_core.entity.resolve.resolve(): aturan normalisasi dan urutan langkah identik.
-- stix_id entitas baru di sini = tipe || '--' || gen_random_uuid() (bukan uuid5 seperti Python):
-- stix_id hanya perlu stabil sejak dibuat; keunikan entitas dijaga lewat lookup alias.
CREATE FUNCTION entity_resolve(p_type text, p_name text, p_source text) RETURNS bigint
LANGUAGE plpgsql AS $fn$
DECLARE
    v_name text := btrim(regexp_replace(p_name, '\s+', ' ', 'g'));
    v_norm text := lower(v_name);
    v_id bigint;
    v_next bigint;
BEGIN
    FOR attempt IN 1..2 LOOP
        SELECT a.entity_id INTO v_id FROM entity_aliases a
         WHERE a.entity_type = p_type AND a.alias_norm = v_norm;
        IF v_id IS NOT NULL THEN
            -- ikuti tombstone merge ke entitas hidup
            LOOP
                SELECT merged_into_id INTO v_next FROM entities WHERE id = v_id;
                EXIT WHEN v_next IS NULL;
                v_id := v_next;
            END LOOP;
            RETURN v_id;
        END IF;

        INSERT INTO entities (type, stix_id, name, source)
        VALUES (p_type, p_type || '--' || gen_random_uuid(), v_name, p_source)
        ON CONFLICT DO NOTHING
        RETURNING id INTO v_id;
        IF v_id IS NULL THEN  -- nama sudah dipakai entitas hidup tanpa alias ini
            SELECT id INTO v_id FROM entities
             WHERE type = p_type AND lower(name) = v_norm AND merged_into_id IS NULL;
        END IF;
        INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
        VALUES (v_id, p_type, v_name, v_norm, p_source)
        ON CONFLICT DO NOTHING;
    END LOOP;
    RAISE EXCEPTION 'entity_resolve gagal untuk % %', p_type, p_name;
END $fn$;
