set default_transaction_read_only = on;
-- Sampel evaluasi Tier 1 (P4): 100 artikel diterima, bukan best practice, maksimal 6 per source PER stratum.
-- Strata: 40 dengan TTP LLM, 20 dengan aktor (tanpa TTP), 40 sisanya. Satu baris JSON per artikel.
-- Kolom `source` per-item (P4) TIDAK dipakai: dev masih 0.8.7 dan kolomnya belum ada.
with c as (
  select a.id, a.url, a.title, a.source, a.victim_name, a.confirmed_incident,
         coalesce((select array_agg(t.threat_actor) from article_threat_actors t
                    where t.article_id = a.id), '{}') as actors,
         coalesce((select json_agg(json_build_object('id', p.ttp_id, 'name', p.ttp_name))
                     from article_ttps p where p.article_id = a.id), '[]'::json) as ttps,
         coalesce((select array_agg(i.industry) from article_industries i
                    where i.article_id = a.id), '{}') as industries,
         random() as r
    from articles a
   where a.news_type is distinct from 'security_tech_best_practice'
     and a.url is not null and a.url <> ''
), s as (
  select c.*,
         case when json_array_length(ttps) > 0 then 1
              when cardinality(actors) > 0 then 2 else 3 end as stratum
    from c
), capped as (
  select s.*, row_number() over (partition by source, stratum order by r) as rn_src from s
), ranked as (
  select capped.*, row_number() over (partition by stratum order by r) as rn
    from capped where rn_src <= 6
)
select json_build_object(
         'id', id, 'url', url, 'title', title, 'source', source,
         'victim_name', victim_name, 'confirmed_incident', confirmed_incident,
         'actors', actors, 'ttps', ttps, 'industries', industries)
  from ranked
 where (stratum = 1 and rn <= 40) or (stratum = 2 and rn <= 20) or (stratum = 3 and rn <= 40);
