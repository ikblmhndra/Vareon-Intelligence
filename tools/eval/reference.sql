set default_transaction_read_only = on;
-- Data rujukan untuk membangun kamus dan katalog Tier 1: satu baris JSON -> reference.json.
select json_build_object(
  'groups', coalesce((select json_agg(json_build_object('name', name, 'aliases', aliases))
                        from attack_groups), '[]'::json),
  'software', coalesce((select json_agg(json_build_object(
                          'name', name, 'software_type', software_type, 'aliases', aliases))
                          from attack_software), '[]'::json),
  'ta_names', coalesce((select json_agg(name) from threat_actor_groups), '[]'::json),
  'suppressed', coalesce((select json_agg(name) from ta_whitelist), '[]'::json),
  'techniques', coalesce((select json_object_agg(attack_id, name) from attack_techniques),
                         '{}'::json));
