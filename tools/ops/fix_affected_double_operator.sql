-- Perbaiki teks `affected` yang diawali "<=" ganda (rilis 0.4.1; PR ikblmhndra/Vareon-Intelligence#24).
--
-- Bentuk rusak: "pkg: <= >= 3.3.0, < 3.5.4", "pkg: <= < 3.2.5", "pkg: <= <= 4.0.3". Sebelum 0.4.1,
-- `parse_cve_record` meng-awali teks versi tulisan CNA (yang sudah memuat operatornya sendiri) dengan "<=".
-- Skrip ini membuang "<= " yang berlebih di dua tempat yang menyimpan teks itu:
--   * `cve_affected.affected`        (tracker; satu string per baris)
--   * `cve_records.affected_lines`   (mirror; JSONB array; sumber promosi `live` ke tracker)
--
-- JALANKAN SESUDAH deploy 0.4.1: kode lama menulis ulang teks rusak pada run `new_cve` berikutnya
-- (CVE 8 hari terakhir). Idempoten. Hanya menyentuh baris yang jelas rusak (awalan "<= " diikuti
-- operator); kalimat bebas seperti "<= All other versions" dibiarkan. Satu pernyataan DO = satu
-- transaksi: bila jumlah baris yang berubah tidak sama dengan yang terhitung, masih ada sisa, atau
-- total baris berubah, SEMUANYA dibatalkan. Cadangan "sebelum": backup Postgres dari `make deploy`
-- tepat sebelumnya.
--
-- Dari checkout di host (perintah yang sama dengan yang dipakai tools/ops/deploy.sh):
--   docker compose --env-file docker/stack.env --profile app exec -T postgres \
--     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -q' < tools/ops/fix_affected_double_operator.sql
\set ON_ERROR_STOP on
\pset footer off
\echo '== sebelum =='
SELECT (SELECT count(*) FROM cve_affected WHERE affected ~ '^.*?: <= [<>=!]') AS affected_rusak,
       (SELECT count(*) FROM cve_records r WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(r.affected_lines) AS l(line)
            WHERE l.line ~ '^.*?: <= [<>=!]')) AS records_rusak;

DO $$
DECLARE
  a_total bigint; a_before bigint; a_changed bigint; a_after bigint; a_total_after bigint;
  r_total bigint; r_before bigint; r_changed bigint; r_after bigint; r_total_after bigint;
BEGIN
  SET LOCAL statement_timeout = '180s';

  SELECT count(*) INTO a_total FROM cve_affected;
  SELECT count(*) INTO a_before FROM cve_affected WHERE affected ~ '^.*?: <= [<>=!]';
  UPDATE cve_affected
     SET affected = regexp_replace(affected, '^(.*?): <= ', '\1: ')
   WHERE affected ~ '^.*?: <= [<>=!]';
  GET DIAGNOSTICS a_changed = ROW_COUNT;
  SELECT count(*) INTO a_after FROM cve_affected WHERE affected ~ '^.*?: <= [<>=!]';
  SELECT count(*) INTO a_total_after FROM cve_affected;

  SELECT count(*) INTO r_total FROM cve_records;
  SELECT count(*) INTO r_before FROM cve_records r WHERE EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(r.affected_lines) AS l(line)
      WHERE l.line ~ '^.*?: <= [<>=!]');
  UPDATE cve_records
     SET affected_lines = (
         SELECT jsonb_agg(
                  CASE WHEN t.line ~ '^.*?: <= [<>=!]'
                       THEN regexp_replace(t.line, '^(.*?): <= ', '\1: ')
                       ELSE t.line END
                  ORDER BY t.ord)
           FROM jsonb_array_elements_text(affected_lines) WITH ORDINALITY AS t(line, ord))
   WHERE EXISTS (
         SELECT 1 FROM jsonb_array_elements_text(affected_lines) AS l(line)
         WHERE l.line ~ '^.*?: <= [<>=!]');
  GET DIAGNOSTICS r_changed = ROW_COUNT;
  SELECT count(*) INTO r_after FROM cve_records r WHERE EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(r.affected_lines) AS l(line)
      WHERE l.line ~ '^.*?: <= [<>=!]');
  SELECT count(*) INTO r_total_after FROM cve_records;

  RAISE NOTICE 'cve_affected: rusak %, diubah %, sisa %, total % -> %', a_before, a_changed, a_after, a_total, a_total_after;
  RAISE NOTICE 'cve_records : rusak %, diubah %, sisa %, total % -> %', r_before, r_changed, r_after, r_total, r_total_after;

  IF a_changed <> a_before OR a_after <> 0 OR a_total <> a_total_after
     OR r_changed <> r_before OR r_after <> 0 OR r_total <> r_total_after THEN
    RAISE EXCEPTION 'pengaman: hasil tidak sesuai harapan, transaksi dibatalkan';
  END IF;
END
$$;

\echo '== sesudah =='
SELECT (SELECT count(*) FROM cve_affected WHERE affected ~ '^.*?: <= [<>=!]') AS affected_rusak,
       (SELECT count(*) FROM cve_records r WHERE EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(r.affected_lines) AS l(line)
            WHERE l.line ~ '^.*?: <= [<>=!]')) AS records_rusak;
