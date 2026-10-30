-- Backfill P7c-1 (spec 3.2 langkah 2-7), set-based, dijalankan sesudah resolve.sql.
-- Normalisasi selalu lewat entity_alias_norm()/entity_collapse_ws() (Ruling 6) supaya alias hasil
-- backfill sama dengan yang dicari resolver.
-- stix_id: objek ATT&CK memakai stix_id ATT&CK; sektor dan negara memakai literal uuid5 yang
-- dihitung generator (entity_stix_id(), nama sudah diketahui saat generate); nama yang datang dari
-- data (aktor lama, CVE, korban, malware, teknik lama) dan relasi ransomware memakai
-- tipe || '--' || gen_random_uuid() karena Postgres inti tidak punya uuid5 (Ruling 5).
-- Kunci tidak memakai titik dua diikuti huruf: op.execute() membungkus file ini dalam text().

-- BEGIN GENERATED (tools/dev/gen_entity_sql.py)
CREATE TEMP TABLE _bf_sectors (external_id text, name text, stix_id text);
INSERT INTO _bf_sectors VALUES
    ('aerospace', 'Aerospace', 'identity--62ff0c52-d7b4-5f76-8613-b8ac8365f452'),
    ('agriculture', 'Agriculture', 'identity--f4a4516b-e630-5c37-9760-cbd46cdf1821'),
    ('automotive', 'Automotive', 'identity--948cb8e4-2c01-5c7c-8ea7-36c287994e25'),
    ('chemical', 'Chemical', 'identity--1d89ee5f-01b6-5552-b618-a8ae3edbde43'),
    ('commercial', 'Commercial', 'identity--14b6f3ce-cfe8-520c-815c-e49985efdc29'),
    ('communications', 'Communications', 'identity--412baa67-c754-521f-8b92-ccaf7a066b12'),
    ('construction', 'Construction', 'identity--3c595b78-1073-563a-b76d-5473aed38856'),
    ('defense', 'Defense', 'identity--d5ec6702-cd50-5d47-9767-a950a6ebae5a'),
    ('education', 'Education', 'identity--d9bbcf32-248a-540b-8d13-00177f90bb0e'),
    ('emergency-services', 'Emergency Services', 'identity--40f1931a-b687-5931-a82d-5e86ec2d2d02'),
    ('energy', 'Energy', 'identity--524b0611-020d-5c81-99f9-f429c4ef52e8'),
    ('entertainment', 'Entertainment', 'identity--7e4f204f-cce8-5263-a17d-3b19b1e38f0a'),
    ('financial-services', 'Financial Services', 'identity--30b071b2-6bad-5b7b-8b94-e405b5f656ad'),
    ('government', 'Government', 'identity--98758cc0-f57a-5db4-af50-fc789e4b8148'),
    ('government-local', 'Government (Local)', 'identity--f80b3e37-6e97-532a-aac3-da5c011b4d53'),
    ('government-national', 'Government (National)', 'identity--baa61f7b-ca99-580f-bbbd-5832727adfd4'),
    ('government-public-services', 'Government (Public Services)', 'identity--75ead40d-0feb-5cdd-8177-1293dd906223'),
    ('government-regional', 'Government (Regional)', 'identity--d0cd1104-c171-5ac3-ab0e-4b7778a1f02f'),
    ('healthcare', 'Healthcare', 'identity--d986aebb-39d7-58a6-99e8-5cb55bce6896'),
    ('hospitality-leisure', 'Hospitality & Leisure', 'identity--765002a2-b8f6-54d9-8970-a73bc87a245b'),
    ('infrastructure', 'Infrastructure', 'identity--de45011f-5189-53ea-91fd-b725cd5a8f30'),
    ('infrastructure-dams', 'Infrastructure (Dams)', 'identity--e49a1087-31a2-5676-a7e6-da3311ae701d'),
    ('infrastructure-nuclear', 'Infrastructure (Nuclear)', 'identity--4364ad85-b192-57a5-ac7a-0ad499ac42b2'),
    ('infrastructure-water', 'Infrastructure (Water)', 'identity--60cff949-8e89-5f02-82df-ae3a3dcce475'),
    ('insurance', 'Insurance', 'identity--29978c7d-7cd9-581f-826a-28ab17468b6b'),
    ('manufacturing', 'Manufacturing', 'identity--59cb39c9-b318-55ff-8824-96d225a0ebd0'),
    ('mining', 'Mining', 'identity--c18eca17-97eb-513a-9ac7-c41725465434'),
    ('non-profit', 'Non-profit', 'identity--1a7a2fea-22d9-5dbe-8c66-0cea31149a79'),
    ('pharmaceuticals', 'Pharmaceuticals', 'identity--79f2525a-941f-54e5-8a2c-bd75ebc7b381'),
    ('retail', 'Retail', 'identity--227d0ba3-d695-52f8-ad03-0db2976dbcb7'),
    ('technology', 'Technology', 'identity--4fc195e4-48e5-5a96-b065-8521752edda9'),
    ('telecommunications', 'Telecommunications', 'identity--0e45c1c9-7e14-5412-b792-b94207c86bf1'),
    ('transportation', 'Transportation', 'identity--cd6fa8d6-9a66-50f7-9c70-b03e349c1ea4'),
    ('utilities', 'Utilities', 'identity--3cfc402c-e581-5da4-8929-794a1e038c83');
CREATE TEMP TABLE _bf_sector_labels (label text, external_id text);
INSERT INTO _bf_sector_labels VALUES
    ('Aerospace & Defense Contractors', 'defense'),
    ('Agriculture & Food', 'agriculture'),
    ('Cloud & Hosting Providers', 'technology'),
    ('Cloud Infrastructure Providers', 'technology'),
    ('Cloud Services', 'technology'),
    ('Critical Infrastructure', 'infrastructure'),
    ('Cryptocurrency & Blockchain', 'financial-services'),
    ('Education & Life Sciences', 'education'),
    ('Education & Research', 'education'),
    ('Energy & Utilities', 'energy'),
    ('Finance & Insurance', 'financial-services'),
    ('Gaming', 'entertainment'),
    ('Government & Public Sector', 'government'),
    ('Healthcare & Life Sciences', 'healthcare'),
    ('Hospitality & Travel', 'hospitality-leisure'),
    ('Information Technology & Software', 'technology'),
    ('Legal & Professional Services', 'commercial'),
    ('Manufacturing & Industrial', 'manufacturing'),
    ('Media & Entertainment', 'entertainment'),
    ('Non-profit & NGOs', 'non-profit'),
    ('Retail & E-commerce', 'retail'),
    ('Science & Research', 'education'),
    ('Security & Professional Services', 'commercial'),
    ('Small Business Operations', 'commercial'),
    ('Technology & Software', 'technology'),
    ('Telecommunications', 'telecommunications'),
    ('Transportation & Logistics', 'transportation');
CREATE TEMP TABLE _bf_countries (code text, name text, stix_id text);
INSERT INTO _bf_countries VALUES
    ('AD', 'Andorra', 'location--0cf779af-3d88-5e86-a1d1-6f1b5aaeda3f'),
    ('AE', 'United Arab Emirates', 'location--6b0d0c66-d078-535f-9d88-5e505853fae0'),
    ('AF', 'Afghanistan', 'location--fc93d35a-cb44-5a54-acfe-95041292d89a'),
    ('AG', 'Antigua and Barbuda', 'location--acb15842-f164-5d4a-b420-321b916316f1'),
    ('AI', 'Anguilla', 'location--406312c3-81a2-59b9-9c81-9a9ef83b6c95'),
    ('AL', 'Albania', 'location--23de9cd5-5e02-5eba-b907-95f1b358508e'),
    ('AM', 'Armenia', 'location--38007b8b-b89f-5f13-ac8f-be7cca91bebc'),
    ('AO', 'Angola', 'location--ec0e458f-47b4-53b9-83bc-a8ca2289ecf2'),
    ('AQ', 'Antarctica', 'location--16e104b1-b526-5cb3-99b5-ccd1e2b1c4e7'),
    ('AR', 'Argentina', 'location--56620bef-77d6-5707-8d4b-91c3a3b2b453'),
    ('AS', 'American Samoa', 'location--d4846017-bd5b-586a-94c6-a153b006c94a'),
    ('AT', 'Austria', 'location--aec7c0e2-3b27-5d41-968e-20eaf161703d'),
    ('AU', 'Australia', 'location--a36a1205-06e9-5f10-b0b4-2cfc30b543b3'),
    ('AW', 'Aruba', 'location--45fccee9-ee79-5f1f-bdb1-6ea8bb6dde02'),
    ('AX', 'Åland Islands', 'location--8dd73638-f4e5-5066-92e7-556cb9b8d830'),
    ('AZ', 'Azerbaijan', 'location--2d2b3241-566b-5b9d-b674-5ce69e87886c'),
    ('BA', 'Bosnia and Herzegovina', 'location--606d2097-2e42-599b-9218-aed65d27ac5f'),
    ('BB', 'Barbados', 'location--47600b9f-172a-519a-a2b7-ba50aa4dd6ed'),
    ('BD', 'Bangladesh', 'location--adccdfde-ef78-52ac-8f46-2bc28bf45f5f'),
    ('BE', 'Belgium', 'location--9c3b16e9-63e9-51cc-9e36-7fb6e2b8a032'),
    ('BF', 'Burkina Faso', 'location--f4b016c4-fa09-53c4-8725-f8f1b28844a0'),
    ('BG', 'Bulgaria', 'location--4dcee98c-7c80-5c83-b3ab-121c83a2ac03'),
    ('BH', 'Bahrain', 'location--9459494d-88d1-5799-92eb-9af7f93a6a4d'),
    ('BI', 'Burundi', 'location--d2e16cf5-c568-56bd-a407-a6a5bc57befd'),
    ('BJ', 'Benin', 'location--f003f5a7-30ac-569e-b1d8-8003dd263ee3'),
    ('BL', 'Saint Barthélemy', 'location--f6487dc7-c61a-5735-ab36-0e87ce96e3ca'),
    ('BM', 'Bermuda', 'location--5961114d-1209-5400-8da5-77d72d16e706'),
    ('BN', 'Brunei Darussalam', 'location--bb2ba1b3-348b-5c24-a721-4c3f61ee67ae'),
    ('BO', 'Bolivia', 'location--c2faa415-efa1-55d3-afb6-0aa748418f97'),
    ('BQ', 'Bonaire, Sint Eustatius and Saba', 'location--e9f8f5a2-7169-584d-869b-d5aaa6060986'),
    ('BR', 'Brazil', 'location--27fe17eb-ef9a-5bf7-815f-647c9f7a700a'),
    ('BS', 'Bahamas', 'location--1545c261-d6d3-555c-8179-a978e5c1f589'),
    ('BT', 'Bhutan', 'location--2263a3b2-4f98-5291-abb1-4763ab3e9099'),
    ('BV', 'Bouvet Island', 'location--06f91b45-574b-5c53-be59-4b2ea540a377'),
    ('BW', 'Botswana', 'location--58f66532-99b9-5943-9a75-151aa186be00'),
    ('BY', 'Belarus', 'location--8c63005a-ffe8-5e1f-b6e4-fad34668e028'),
    ('BZ', 'Belize', 'location--b6adf36b-4e31-55d2-82df-79c1c94b5aaa'),
    ('CA', 'Canada', 'location--143f3a32-f5fe-59dc-9649-b4f26c7f305f'),
    ('CC', 'Cocos (Keeling) Islands', 'location--320a8e44-f7bf-5fbf-a066-79c343fa8999'),
    ('CD', 'Congo, The Democratic Republic of the', 'location--656581a9-185c-5f5e-8068-6c276ca13591'),
    ('CF', 'Central African Republic', 'location--5c5d741c-9960-51de-bae0-ab103a0f58c3'),
    ('CG', 'Congo', 'location--e2b64caf-06e4-5d85-bc9d-eef592d36f80'),
    ('CH', 'Switzerland', 'location--f1ddc7ae-0bab-5722-aa8f-0e8505701266'),
    ('CI', 'Côte d''Ivoire', 'location--ea55e4a5-bd22-534e-bb80-726b20cbaeb1'),
    ('CK', 'Cook Islands', 'location--2b6119dc-a9b8-52ee-9546-32b9bf518844'),
    ('CL', 'Chile', 'location--6500eb59-d7b5-5f61-8c8f-2a88971610ae'),
    ('CM', 'Cameroon', 'location--d04f9e4e-7025-5591-98e0-74e83928f860'),
    ('CN', 'China', 'location--d6ac5094-eb07-5146-9235-a77218aae384'),
    ('CO', 'Colombia', 'location--16954c11-d32a-5d9e-8f6b-38701890169a'),
    ('CR', 'Costa Rica', 'location--32f5730c-ef39-5637-852a-80ef6114be28'),
    ('CU', 'Cuba', 'location--2e40b92f-209e-5ab5-9aeb-180751694919'),
    ('CV', 'Cabo Verde', 'location--3593c332-9270-5960-a498-bcb1a1b8fdda'),
    ('CW', 'Curaçao', 'location--820140d0-5b3c-5bcc-ae77-fef8b89616d1'),
    ('CX', 'Christmas Island', 'location--668355dd-9edd-5258-8aa7-1123f7410225'),
    ('CY', 'Cyprus', 'location--b3e0eb47-ee97-5c06-92ce-dc7f106f48ab'),
    ('CZ', 'Czechia', 'location--fdf80b0c-87fd-5f09-8413-a19cdc7273a3'),
    ('DE', 'Germany', 'location--f06661f5-8191-5aaf-bad2-1ee53e267d43'),
    ('DJ', 'Djibouti', 'location--bb356a1b-6751-5c38-8b1e-003111d0a12a'),
    ('DK', 'Denmark', 'location--c2789537-c000-51c9-b4b5-1c40e2084a7a'),
    ('DM', 'Dominica', 'location--dcb44161-6d75-53bd-9580-4ac3bed24053'),
    ('DO', 'Dominican Republic', 'location--aadafd37-0a17-5745-afc8-bb261339a56a'),
    ('DZ', 'Algeria', 'location--de8df136-0396-5279-99ab-789d5df03aee'),
    ('EC', 'Ecuador', 'location--8ae03603-cc79-534f-b5d2-7c2da2b7afa5'),
    ('EE', 'Estonia', 'location--0b7c6104-5726-523f-9e5f-f483401f044e'),
    ('EG', 'Egypt', 'location--24aea8f0-073a-56c5-b318-1580348f9090'),
    ('EH', 'Western Sahara', 'location--4a8411ac-e12d-56f8-8491-97ad95dca3b7'),
    ('ER', 'Eritrea', 'location--3f1be09e-fdc4-521f-b09e-ac2515e79c94'),
    ('ES', 'Spain', 'location--281cf04d-33ce-5f97-a06f-c10e59524621'),
    ('ET', 'Ethiopia', 'location--13cb35ee-a023-54da-8a85-bee1b1d44d10'),
    ('FI', 'Finland', 'location--d29670b9-3597-5d63-8f21-328dc6d17267'),
    ('FJ', 'Fiji', 'location--059d02ef-b9e1-5407-a3bf-55a34bcfc1f8'),
    ('FK', 'Falkland Islands (Malvinas)', 'location--60d1d00f-ac28-5095-b1a4-bc695923666b'),
    ('FM', 'Micronesia, Federated States of', 'location--b89b60ac-271c-5a8e-ac76-564fa6e2dc84'),
    ('FO', 'Faroe Islands', 'location--f5a73017-f73d-5fc1-b7c5-d00ff9352afa'),
    ('FR', 'France', 'location--b8f1d736-707a-577b-9859-85aaa7f52df4'),
    ('GA', 'Gabon', 'location--6b0d691d-dbb4-5eac-8ae3-b6bf5c7aed64'),
    ('GB', 'United Kingdom', 'location--1af9b916-fa3b-51f3-ad78-2b311f737bd3'),
    ('GD', 'Grenada', 'location--af9ab84a-9098-5545-b581-8ef80d707df1'),
    ('GE', 'Georgia', 'location--636e9c3e-36a5-5d0e-8eb7-b6c9d8a04e25'),
    ('GF', 'French Guiana', 'location--c58ad50e-463d-51dd-893a-7c3bab67aa82'),
    ('GG', 'Guernsey', 'location--9f6182b5-bd37-581a-99a2-1ee73dac6952'),
    ('GH', 'Ghana', 'location--d3a7ab1e-b567-5dab-97a1-804cab710559'),
    ('GI', 'Gibraltar', 'location--fc929efe-96b0-5f76-a885-5eae1c043f23'),
    ('GL', 'Greenland', 'location--00bc3dbc-0a63-5194-91f2-1624d6c15488'),
    ('GM', 'Gambia', 'location--45517c5d-e9d6-5f87-8280-909b7f853cc1'),
    ('GN', 'Guinea', 'location--1c70ee67-e4a8-53dc-b18d-3431a783135f'),
    ('GP', 'Guadeloupe', 'location--f542dd38-7b39-5e5a-bfea-c880a9e8883e'),
    ('GQ', 'Equatorial Guinea', 'location--467427bd-d3f2-521a-9fab-7405ce69d38e'),
    ('GR', 'Greece', 'location--511f6c7d-0a73-5243-9563-0b6b441050d4'),
    ('GS', 'South Georgia and the South Sandwich Islands', 'location--83581e2a-56f9-5f37-bb10-d813290cd9c5'),
    ('GT', 'Guatemala', 'location--b6dc5912-1664-5d67-ac1a-a18898b8366c'),
    ('GU', 'Guam', 'location--f624358d-ac06-53e3-b7c8-a6e748a204e6'),
    ('GW', 'Guinea-Bissau', 'location--b794f735-e24c-58e3-96f5-e7f2885ba067'),
    ('GY', 'Guyana', 'location--9dfdd39c-f66d-5312-ab1a-01474ed7c2d8'),
    ('HK', 'Hong Kong', 'location--9f3bb36c-5b4b-53a4-a66b-9d777c190727'),
    ('HM', 'Heard Island and McDonald Islands', 'location--0a3a41d2-45fe-52e1-bbf8-d218f717fc77'),
    ('HN', 'Honduras', 'location--4ff677db-0f2f-5124-b148-2011c16b2c78'),
    ('HR', 'Croatia', 'location--65b80821-45fc-5da9-ba8e-88394384821b'),
    ('HT', 'Haiti', 'location--3f88faea-58a7-53f1-9d08-9d76f0184f4e'),
    ('HU', 'Hungary', 'location--ae229158-7e35-56d5-b80a-ee4364991711'),
    ('ID', 'Indonesia', 'location--9efbb1e3-aa01-5417-afed-86d2a7288ae9'),
    ('IE', 'Ireland', 'location--cdc0de55-4282-57e0-9c57-d3ec4c6d08ef'),
    ('IL', 'Israel', 'location--5bbf0861-3908-5d60-b21e-f3aae9d8757a'),
    ('IM', 'Isle of Man', 'location--ebf51353-79c2-5f16-b23c-c673e0401f59'),
    ('IN', 'India', 'location--eec79fd4-d707-5c1d-89b0-4cf88cfd6279'),
    ('IO', 'British Indian Ocean Territory', 'location--709c362c-60d0-549d-a8c0-491f7da2076c'),
    ('IQ', 'Iraq', 'location--338c69c8-32fe-5de0-99b4-f10db21ee3a7'),
    ('IR', 'Iran', 'location--1879b706-b5a1-580a-bfa4-be5191e24db4'),
    ('IS', 'Iceland', 'location--e0081987-2bf9-5d5d-a193-9419b80b01fe'),
    ('IT', 'Italy', 'location--3a3fb20e-52e6-5ab7-b185-3920ec095932'),
    ('JE', 'Jersey', 'location--26b96bca-ba9c-5499-8091-74fbf32edae4'),
    ('JM', 'Jamaica', 'location--8c20253b-7cb2-52bb-81ce-c0e9a13863fb'),
    ('JO', 'Jordan', 'location--302a66ef-2c8c-525a-bc65-594afb91e353'),
    ('JP', 'Japan', 'location--e9a3f4a9-7293-5920-a900-b6e5d616cb84'),
    ('KE', 'Kenya', 'location--0622255f-946a-5b9d-941e-518927f73522'),
    ('KG', 'Kyrgyzstan', 'location--5e6da801-2a98-5d43-8467-198a9e719575'),
    ('KH', 'Cambodia', 'location--10868cb4-c5cb-555e-b663-f6ff9641328e'),
    ('KI', 'Kiribati', 'location--9fe9deaf-26ab-5a92-a20a-6899269ea45d'),
    ('KM', 'Comoros', 'location--596d7acd-e492-576a-bd7e-b9c99c2401c1'),
    ('KN', 'Saint Kitts and Nevis', 'location--9fb2fdd9-d3fd-5aa6-808f-b26f1cb53f11'),
    ('KP', 'North Korea', 'location--1b859419-dbd6-5d96-bc6f-21ec15da170b'),
    ('KR', 'South Korea', 'location--43476c9e-5b39-55de-b164-1e79bb524d51'),
    ('KW', 'Kuwait', 'location--a9e83720-04a4-5309-81da-b714a843924a'),
    ('KY', 'Cayman Islands', 'location--6c14ef6f-6291-58b5-a2ad-23b91791b21d'),
    ('KZ', 'Kazakhstan', 'location--af88a564-9f22-5757-a5de-1ac89bae4f60'),
    ('LA', 'Laos', 'location--2bfd9e39-2fcb-503c-9323-e8f3f0d98fcc'),
    ('LB', 'Lebanon', 'location--d5b45648-d2ee-5b1a-ad60-c172b13dca75'),
    ('LC', 'Saint Lucia', 'location--3d5eec00-72b9-5c45-bcf8-d7ae4b2516d1'),
    ('LI', 'Liechtenstein', 'location--aca39094-af28-571d-aba6-d7948d686b4b'),
    ('LK', 'Sri Lanka', 'location--259dc2ec-fa6c-589c-8155-3470779ab8ec'),
    ('LR', 'Liberia', 'location--bed8b670-4526-56db-9376-fd489e8f92b0'),
    ('LS', 'Lesotho', 'location--37460e89-99ed-5d13-b930-97b2409f0c45'),
    ('LT', 'Lithuania', 'location--c9db267e-db5d-5f49-b824-9e3eaeba75a7'),
    ('LU', 'Luxembourg', 'location--3bcaff40-d1cf-51b2-96dc-469e4135dd56'),
    ('LV', 'Latvia', 'location--f65fbc74-bb44-599e-9ee6-094a8da9a69b'),
    ('LY', 'Libya', 'location--c11b27b7-e9fc-5ec2-befe-799f3e44bb54'),
    ('MA', 'Morocco', 'location--5f176c23-a4b2-5c64-86c7-86c2a7cf3291'),
    ('MC', 'Monaco', 'location--9da02993-30d3-5266-a8d4-785d97739212'),
    ('MD', 'Moldova', 'location--0e795937-5786-5725-97b0-540002ae550f'),
    ('ME', 'Montenegro', 'location--949213cd-3dd4-5512-bdb9-e4f8c72083e2'),
    ('MF', 'Saint Martin (French part)', 'location--16539eca-dfcf-5b91-9040-77cb00e33fe2'),
    ('MG', 'Madagascar', 'location--20a7df5e-f7d7-579a-9e75-06cd783fc613'),
    ('MH', 'Marshall Islands', 'location--cf45971e-8a94-5014-9e91-391bdd8542f1'),
    ('MK', 'North Macedonia', 'location--c31d10f6-5c1f-5924-a547-9343b307117e'),
    ('ML', 'Mali', 'location--7768a87f-a1b5-5373-97f9-11c6adb47ee1'),
    ('MM', 'Myanmar', 'location--42ed1524-24f0-5b27-9629-024d5716787e'),
    ('MN', 'Mongolia', 'location--a2346bfd-0909-5b6a-a8ee-3e7df69ad523'),
    ('MO', 'Macao', 'location--0c785aa4-98ed-5fc2-a2aa-a54ecfe60557'),
    ('MP', 'Northern Mariana Islands', 'location--673f698c-3049-58d9-91df-5ca80bcd08f5'),
    ('MQ', 'Martinique', 'location--8cc62b47-1434-5b9d-ab44-78c9d7b8886e'),
    ('MR', 'Mauritania', 'location--4a236ecd-a0ab-5bb2-985d-ffd3be0d9a20'),
    ('MS', 'Montserrat', 'location--be6cd342-15f8-535f-94ea-5c496836ce95'),
    ('MT', 'Malta', 'location--4fb42b95-2da3-5691-9796-66ce33c0a7bd'),
    ('MU', 'Mauritius', 'location--7fc19576-a7c0-5568-b78b-376210563ecb'),
    ('MV', 'Maldives', 'location--fe5bf55a-9c19-5366-a765-e7a91ac74685'),
    ('MW', 'Malawi', 'location--f539ce81-8aef-5c6e-a4e4-dc419f6845e0'),
    ('MX', 'Mexico', 'location--27b8730b-de81-5d39-bda5-68c3e5385652'),
    ('MY', 'Malaysia', 'location--0133357f-e906-568f-9110-8ea1a46c8e5e'),
    ('MZ', 'Mozambique', 'location--9885d58f-b516-591c-b636-a4192052dfed'),
    ('NA', 'Namibia', 'location--30b04623-10f7-5aac-a46c-2e2df7bfad72'),
    ('NC', 'New Caledonia', 'location--665986b8-14d2-5026-a25b-05dcfa23c8b7'),
    ('NE', 'Niger', 'location--5e356f58-a778-59e8-9502-852eba2c6f60'),
    ('NF', 'Norfolk Island', 'location--84856150-eff6-5a3d-bbc3-0ed2cc2aa546'),
    ('NG', 'Nigeria', 'location--5da7bf4c-90cc-5cdf-a838-cd5a5ed1277a'),
    ('NI', 'Nicaragua', 'location--ac669825-6c10-5fdb-895c-b4893e50feea'),
    ('NL', 'Netherlands', 'location--e08f2e98-3a42-55f8-98c5-35f6d7aee0ee'),
    ('NO', 'Norway', 'location--64184940-4e9c-5c99-9e25-4d60751400db'),
    ('NP', 'Nepal', 'location--2cd8e94d-1100-5c13-bb78-096141aea6fb'),
    ('NR', 'Nauru', 'location--1ca70ab4-8635-5ea8-b179-06ceb80db3d5'),
    ('NU', 'Niue', 'location--7db279c1-f879-5e8d-96a0-3eda88051f22'),
    ('NZ', 'New Zealand', 'location--7221bceb-e569-52d8-a13c-3cbbedf7e6b2'),
    ('OM', 'Oman', 'location--87690323-0223-562c-8bad-4814ee274c29'),
    ('PA', 'Panama', 'location--491416a8-2729-58a7-8ab2-01fca814b02d'),
    ('PE', 'Peru', 'location--3dd61b54-fb3e-5f26-8528-d52afc4ffa0a'),
    ('PF', 'French Polynesia', 'location--5b8b14ef-e6db-5a0b-b610-69662b9755af'),
    ('PG', 'Papua New Guinea', 'location--9cef6174-e042-566e-aef3-0767944c0ae0'),
    ('PH', 'Philippines', 'location--4b9d2e6a-eff6-5d83-871f-b5f1296d99d4'),
    ('PK', 'Pakistan', 'location--e2ed4899-021b-5961-bc3e-bdff521715fe'),
    ('PL', 'Poland', 'location--25bad3fc-b246-5681-ab51-560751e16cc2'),
    ('PM', 'Saint Pierre and Miquelon', 'location--334ed092-dfe9-5830-90c6-0d934688a994'),
    ('PN', 'Pitcairn', 'location--183f3bda-f49a-5489-9707-f3503dfb94d2'),
    ('PR', 'Puerto Rico', 'location--14e2e835-23d9-5a09-8746-e5d5d6ca0de3'),
    ('PS', 'Palestine, State of', 'location--8bf40fbf-6e27-5f96-8b32-9fe1262a8989'),
    ('PT', 'Portugal', 'location--ae28c3cb-2cd7-5ab9-a371-16fe3305bcdf'),
    ('PW', 'Palau', 'location--05783274-35dd-53b2-966a-06b098553916'),
    ('PY', 'Paraguay', 'location--8572488b-6e19-52e1-b3bf-3b63b7b6feaf'),
    ('QA', 'Qatar', 'location--cc3a7c88-2cd5-5e8b-87f8-351bb2fdb57b'),
    ('RE', 'Réunion', 'location--9363cd87-fe3c-5bf9-ba87-6e0ea39ec69c'),
    ('RO', 'Romania', 'location--13b8df6b-6454-5900-956d-c9056dcf214f'),
    ('RS', 'Serbia', 'location--3f37db2e-0182-5a53-bafe-c9095f234a1a'),
    ('RU', 'Russian Federation', 'location--63f5e2e8-61a9-57ef-8c37-7375989a2325'),
    ('RW', 'Rwanda', 'location--b44287b1-ec04-5b74-a70a-8da37a19be05'),
    ('SA', 'Saudi Arabia', 'location--bfba00b2-85ec-5017-b4c5-ecff6e027fb3'),
    ('SB', 'Solomon Islands', 'location--ec6c4cb2-4f18-5792-8dc1-5feeca6a805f'),
    ('SC', 'Seychelles', 'location--9e210e33-10b1-5257-88c1-909ef17ebffe'),
    ('SD', 'Sudan', 'location--20e485fc-5ac3-536b-9498-df3cd52dac76'),
    ('SE', 'Sweden', 'location--8cbf1740-2360-5d88-b8c5-735b008f3008'),
    ('SG', 'Singapore', 'location--617c90e7-4857-5cdc-9dc4-2ee3d937201c'),
    ('SH', 'Saint Helena, Ascension and Tristan da Cunha', 'location--5f0e0e1a-287e-5e9b-9246-ef1cbdc96920'),
    ('SI', 'Slovenia', 'location--b6820915-bc43-5fcf-a915-85f0b295341a'),
    ('SJ', 'Svalbard and Jan Mayen', 'location--9d3dd289-5e42-5a7c-ab23-5989cf0441a8'),
    ('SK', 'Slovakia', 'location--941bd420-0d06-5280-acff-f93888e7653f'),
    ('SL', 'Sierra Leone', 'location--353e8991-b5ee-5b84-ab63-196b487eb7a5'),
    ('SM', 'San Marino', 'location--2fcde436-90f3-5610-81d0-8da4920bd7dc'),
    ('SN', 'Senegal', 'location--f59f18ca-118d-55da-9593-af0928283d87'),
    ('SO', 'Somalia', 'location--218a157b-010a-548d-9a44-5e0c1d3387f3'),
    ('SR', 'Suriname', 'location--b121cf06-b41e-5198-86b9-c8a397ea96e2'),
    ('SS', 'South Sudan', 'location--879c9128-0dbc-537f-8b1e-65b5036f10ba'),
    ('ST', 'Sao Tome and Principe', 'location--69f15340-9216-54e5-809e-cfd76e8ad4bb'),
    ('SV', 'El Salvador', 'location--0e9c39f2-45bb-582c-a72e-6c108074bd1f'),
    ('SX', 'Sint Maarten (Dutch part)', 'location--936de95f-d778-5637-80b2-505b9d0bd509'),
    ('SY', 'Syria', 'location--dfd27fe2-4410-5ee9-b2a3-2e0b5514003c'),
    ('SZ', 'Eswatini', 'location--553fb47f-bee4-57a2-8f45-3f8c33428aee'),
    ('TC', 'Turks and Caicos Islands', 'location--7b7802fc-5811-5001-a4cf-bf459e47c5d7'),
    ('TD', 'Chad', 'location--78e4cef7-653f-5954-aa33-5ada8942aab5'),
    ('TF', 'French Southern Territories', 'location--880ebd7e-c1ef-5b4a-9652-633bdc8869c0'),
    ('TG', 'Togo', 'location--c61597a9-3f02-5bc0-b068-e9420f37417e'),
    ('TH', 'Thailand', 'location--0bf4f5d4-31ac-5667-a20c-18e1e027d12e'),
    ('TJ', 'Tajikistan', 'location--708b600e-7402-58df-ba57-d4d8833a4222'),
    ('TK', 'Tokelau', 'location--f63437a6-116c-57b6-ad4c-b747f3cc2dce'),
    ('TL', 'Timor-Leste', 'location--0959b0df-69ad-597a-b24f-fbe7ec0328dd'),
    ('TM', 'Turkmenistan', 'location--2b246656-b0cd-5dbb-b0d4-72bf9ac78ebe'),
    ('TN', 'Tunisia', 'location--743755dd-ca7c-562b-a77f-d8086a39d958'),
    ('TO', 'Tonga', 'location--710ee9c0-72d5-53eb-8871-922bc04c9997'),
    ('TR', 'Türkiye', 'location--d26c6752-bce4-5c26-af72-24fb16c870e1'),
    ('TT', 'Trinidad and Tobago', 'location--9919882e-3956-53bd-8147-b5bde22cb7c5'),
    ('TV', 'Tuvalu', 'location--92eb0dd6-351b-5da3-b389-52463dbd3e4d'),
    ('TW', 'Taiwan', 'location--da7b3940-4b39-5b1f-8dd2-a37b6a00d4fc'),
    ('TZ', 'Tanzania', 'location--c5e85d64-eb4f-5ff3-b813-130f4034e0b1'),
    ('UA', 'Ukraine', 'location--2db9f81f-6cab-587d-8f86-e430b00e5107'),
    ('UG', 'Uganda', 'location--c1f2461b-b8b6-55f3-b78b-232bc1cd14a5'),
    ('UM', 'United States Minor Outlying Islands', 'location--a6868643-65be-5291-8b16-deaa5f45fbf9'),
    ('US', 'United States', 'location--f75cb24c-35ae-5aa0-a39e-945733fff5bd'),
    ('UY', 'Uruguay', 'location--9c8d688c-164c-5020-a756-e2c98ef080ba'),
    ('UZ', 'Uzbekistan', 'location--a4d6a755-7d68-521c-82d4-5985d9187fd1'),
    ('VA', 'Holy See (Vatican City State)', 'location--d6829c6e-5548-5930-8b98-93fbdee666ca'),
    ('VC', 'Saint Vincent and the Grenadines', 'location--4538bf66-b8d0-572e-acf0-cd19ad15ee2a'),
    ('VE', 'Venezuela', 'location--2c60fad3-da4c-5d35-994b-2a2e6fa65d78'),
    ('VG', 'Virgin Islands, British', 'location--c9f7bac0-856a-5d5a-bd6d-1188f31616c7'),
    ('VI', 'Virgin Islands, U.S.', 'location--8ca0d40c-847d-5d96-942d-d271fc54b89c'),
    ('VN', 'Vietnam', 'location--e9e4cd8b-cc42-5e9b-9866-9db43829314f'),
    ('VU', 'Vanuatu', 'location--97cf887e-ba35-5436-b9d2-3d7b529de1ad'),
    ('WF', 'Wallis and Futuna', 'location--b8a5065d-b024-5c54-a321-413ecc3398a3'),
    ('WS', 'Samoa', 'location--148a68e7-a68d-5033-9cdc-611235ae0019'),
    ('YE', 'Yemen', 'location--9159744b-e7cd-555a-b51a-334dc5d56ee0'),
    ('YT', 'Mayotte', 'location--3d057551-5539-5806-8cce-2cc4f23cfdd4'),
    ('ZA', 'South Africa', 'location--132894f6-4515-5dbb-8ffd-74fdcf5256d9'),
    ('ZM', 'Zambia', 'location--0e67b804-303d-5365-b9e9-491bf0698fb6'),
    ('ZW', 'Zimbabwe', 'location--8dc53329-c247-55e4-8ac4-6e4545caa6f1');
-- END GENERATED

-- 2. ATT&CK -> entitas, alias (source=attack), relasi (provenance=attack, confidence 85).
-- Bentrok dilewati (ON CONFLICT DO NOTHING), yang pertama menurut stix_id menang: grup (nama
-- atau group_id kembar), software (nama kembar per tipe, mis. lintas domain), teknik (attack_id
-- kembar). Daftar yang terlewat (query laporan, jalankan manual sesudah migrasi):
--   SELECT 'group' AS kind, stix_id, group_id AS ext, name FROM attack_groups x
--    WHERE NOT EXISTS (SELECT 1 FROM entities e WHERE e.stix_id = x.stix_id)
--   UNION ALL SELECT 'software', stix_id, software_id, name FROM attack_software x
--    WHERE NOT EXISTS (SELECT 1 FROM entities e WHERE e.stix_id = x.stix_id)
--   UNION ALL SELECT 'technique', stix_id, attack_id, name FROM attack_techniques x
--    WHERE NOT EXISTS (SELECT 1 FROM entities e WHERE e.stix_id = x.stix_id);
INSERT INTO entities (type, stix_id, name, description, external_id, source)
SELECT 'intrusion-set', stix_id, entity_collapse_ws(name), nullif(description, ''),
       nullif(group_id, ''), 'attack'
  FROM attack_groups WHERE entity_alias_norm(name) <> ''
 ORDER BY stix_id
ON CONFLICT DO NOTHING;

INSERT INTO entities (type, stix_id, name, description, external_id, source)
SELECT CASE WHEN software_type = 'tool' THEN 'tool' ELSE 'malware' END, stix_id,
       entity_collapse_ws(name), nullif(description, ''), nullif(software_id, ''), 'attack'
  FROM attack_software WHERE entity_alias_norm(name) <> ''
 ORDER BY stix_id
ON CONFLICT DO NOTHING;

-- identitas teknik = id teknik (Ruling 7): nama boleh kembar, alias hanya id teknik
INSERT INTO entities (type, stix_id, name, description, external_id, source)
SELECT 'attack-pattern', stix_id, entity_collapse_ws(name), nullif(description, ''),
       upper(entity_collapse_ws(attack_id)), 'attack'
  FROM attack_techniques WHERE entity_alias_norm(attack_id) <> ''
 ORDER BY stix_id
ON CONFLICT DO NOTHING;

-- alias resmi: nama sendiri dulu, lalu alias; alias yang dipakai dua objek -> pemilik pertama
INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
SELECT DISTINCT ON (e.type, entity_alias_norm(x.alias))
       e.id, e.type, entity_collapse_ws(x.alias), entity_alias_norm(x.alias), 'attack'
  FROM (SELECT stix_id, name AS alias, 0 AS ord FROM attack_groups
        UNION ALL SELECT stix_id, unnest(aliases), 1 FROM attack_groups
        UNION ALL SELECT stix_id, name, 0 FROM attack_software
        UNION ALL SELECT stix_id, unnest(aliases), 1 FROM attack_software) x
  JOIN entities e ON e.stix_id = x.stix_id
 WHERE entity_alias_norm(x.alias) <> ''
 ORDER BY e.type, entity_alias_norm(x.alias), x.ord, x.stix_id
ON CONFLICT DO NOTHING;

INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
SELECT id, type, external_id, entity_alias_norm(external_id), 'attack'
  FROM entities WHERE type = 'attack-pattern'
ON CONFLICT DO NOTHING;

-- revoked-by, detects, mitigates, x-mitre-* dan relasi ke objek yang tidak disimpan (campaign)
-- tetap hanya di attack_relationships
INSERT INTO relationships (stix_id, relationship_type, source_entity_id, target_entity_id,
                           confidence, provenance, description)
SELECT r.stix_id, r.relationship_type, s.id, t.id, 85, 'attack', nullif(r.description, '')
  FROM attack_relationships r
  JOIN entities s ON s.stix_id = r.source_ref
  JOIN entities t ON t.stix_id = r.target_ref
 WHERE r.relationship_type IN ('uses', 'targets', 'attributed-to', 'exploits', 'indicates',
                               'variant-of', 'located-at', 'related-to', 'subtechnique-of')
 ORDER BY r.stix_id
ON CONFLICT DO NOTHING;

-- 3a. Referensi statis: semua sektor (vocab STIX) dan negara ISO, supaya label lama dan kode
-- negara dari kode lama (atau view kompatibilitas) selalu menemukan entitas yang sama.
INSERT INTO entities (type, stix_id, name, external_id, identity_class, source)
SELECT 'identity', stix_id, name, external_id, 'class', 'sector' FROM _bf_sectors
 ORDER BY external_id
ON CONFLICT DO NOTHING;

INSERT INTO entities (type, stix_id, name, external_id, source)
SELECT 'location', stix_id, name, code, 'iso' FROM _bf_countries
 ORDER BY code
ON CONFLICT DO NOTHING;

-- alias sektor: nama tampilan + label industri lama (spec 3.3); negara: nama ISO
INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
SELECT DISTINCT ON (e.type, entity_alias_norm(x.alias))
       e.id, e.type, x.alias, entity_alias_norm(x.alias), 'legacy'
  FROM (SELECT external_id, name AS alias, 0 AS ord FROM _bf_sectors
        UNION ALL SELECT external_id, label, 1 FROM _bf_sector_labels) x
  JOIN entities e ON e.type = 'identity' AND e.source = 'sector' AND e.external_id = x.external_id
 ORDER BY e.type, entity_alias_norm(x.alias), x.ord, x.external_id
ON CONFLICT DO NOTHING;

INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
SELECT e.id, e.type, e.name, entity_alias_norm(e.name), 'legacy'
  FROM entities e WHERE e.type = 'location' AND e.source = 'iso'
 ORDER BY e.external_id
ON CONFLICT DO NOTHING;

-- kode negara di luar tabel ISO -> lokasi legacy (nama = kode)
INSERT INTO entities (type, stix_id, name, external_id, source)
SELECT 'location', 'location--' || gen_random_uuid(), c.code, c.code, 'legacy'
  FROM (SELECT upper(btrim(country_code)) AS code FROM article_countries
        UNION SELECT upper(btrim(country_code)) FROM ransomware_victims
         WHERE country_code IS NOT NULL) c
 WHERE c.code <> ''
   AND NOT EXISTS (SELECT 1 FROM entities e WHERE e.type = 'location' AND e.external_id = c.code)
 ORDER BY c.code
ON CONFLICT DO NOTHING;

INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
SELECT id, type, name, entity_alias_norm(name), 'legacy'
  FROM entities WHERE type = 'location' AND source = 'legacy'
ON CONFLICT DO NOTHING;

-- 3b. Nama dari tabel lama: cocokkan alias per tipe; yang tidak cocok jadi entitas baru dengan
-- nama string lama. Bila beberapa ejaan menormalisasi sama, nama tampilan = ejaan dari
-- sumber prio terkecil, lalu baris lama paling awal (ord).
CREATE TEMP TABLE _bf_names (type text, name text, source text, identity_class text, prio int,
                             ord bigint);
INSERT INTO _bf_names
SELECT 'intrusion-set', threat_actor, 'legacy', NULL, 1, id FROM article_threat_actors
UNION ALL SELECT 'intrusion-set', threat_actor, 'legacy', NULL, 2, id FROM indicator_threat_actors
UNION ALL SELECT 'intrusion-set', threat_actor, 'legacy', NULL, 3, id FROM cve_threat_actors
UNION ALL SELECT 'intrusion-set', name, 'legacy', NULL, 4, id FROM ta_watchlist
UNION ALL SELECT 'intrusion-set', actor_name, 'legacy', NULL, 5, id FROM ta_profiles
UNION ALL SELECT 'intrusion-set', name, 'legacy', NULL, 6, id FROM ta_whitelist
UNION ALL SELECT 'intrusion-set', group_name, 'legacy', NULL, 7, id FROM ransomware_victims
-- isian bebas pengguna: hanya elemen string, dipotong ke panjang kolom; kunci hilang atau bukan
-- array -> tidak ada apa-apa (tanpa error)
UNION ALL SELECT 'intrusion-set', left(x.e #>> '{}', 300), 'legacy', NULL, 8, p.id
            FROM pir_requirements p
           CROSS JOIN LATERAL jsonb_array_elements(
                 CASE WHEN jsonb_typeof(p.criteria -> 'threat_actors') = 'array'
                      THEN p.criteria -> 'threat_actors' ELSE '[]'::jsonb END) AS x(e)
           WHERE jsonb_typeof(x.e) = 'string'
UNION ALL SELECT CASE WHEN kind = 'tool' THEN 'tool' ELSE 'malware' END, name, 'legacy', NULL, 1,
                 id
            FROM article_malware
UNION ALL SELECT 'vulnerability', cve_id, 'cve', NULL, 1, article_id FROM article_cves
UNION ALL SELECT 'vulnerability', cve_id, 'cve', NULL, 2, id FROM cve_tracker
-- label industri: lewat alias sektor; label tak dikenal -> identitas sektor legacy;
-- "General" tidak menghasilkan apa-apa (spec 3.3)
UNION ALL SELECT 'identity', industry, 'legacy', 'class', 1, id FROM article_industries
UNION ALL SELECT 'identity', industry, 'legacy', 'class', 2, id FROM ransomware_victims
           WHERE industry IS NOT NULL
-- korban dipotong ke panjang kolom entities.name (ransomware_victims.victim varchar(500))
UNION ALL SELECT 'identity', left(victim, 300), 'ransomware', 'organization', 3, id
            FROM ransomware_victims;
DELETE FROM _bf_names WHERE name IS NULL OR entity_alias_norm(name) = ''
    OR (identity_class = 'class' AND entity_alias_norm(name) = 'general');

INSERT INTO entities (type, stix_id, name, source, identity_class, external_id)
SELECT DISTINCT ON (n.type, entity_alias_norm(n.name))
       n.type, n.type || '--' || gen_random_uuid(), entity_collapse_ws(n.name), n.source,
       n.identity_class,
       CASE WHEN n.type = 'vulnerability' THEN entity_collapse_ws(n.name) END
  FROM _bf_names n
 WHERE NOT EXISTS (SELECT 1 FROM entity_aliases a
                    WHERE a.entity_type = n.type AND a.alias_norm = entity_alias_norm(n.name))
 ORDER BY n.type, entity_alias_norm(n.name), n.prio, n.ord, n.name
ON CONFLICT DO NOTHING;

INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
SELECT DISTINCT ON (n.type, entity_alias_norm(n.name))
       e.id, n.type, entity_collapse_ws(n.name), entity_alias_norm(n.name), 'legacy'
  FROM _bf_names n
  JOIN entities e ON e.type = n.type AND lower(e.name) = entity_alias_norm(n.name)
                 AND e.merged_into_id IS NULL
 ORDER BY n.type, entity_alias_norm(n.name), n.prio, n.ord, n.name
ON CONFLICT DO NOTHING;

-- teknik dari tabel lama: lewat id teknik; id yang tak dikenal (termasuk id revoked) -> teknik
-- legacy dengan kunci id lama dan nama lama (Ruling 8)
INSERT INTO entities (type, stix_id, name, external_id, source)
SELECT DISTINCT ON (entity_alias_norm(t.ttp_id))
       'attack-pattern', 'attack-pattern--' || gen_random_uuid(),
       coalesce(nullif(entity_collapse_ws(t.ttp_name), ''), entity_collapse_ws(t.ttp_id)),
       upper(entity_collapse_ws(t.ttp_id)), 'legacy'
  FROM (SELECT ttp_id, ttp_name, 1 AS prio, id FROM article_ttps
        UNION ALL SELECT ttp_id, ttp_name, 2, id FROM cve_ttps) t
 WHERE entity_alias_norm(t.ttp_id) <> ''
   AND NOT EXISTS (SELECT 1 FROM entity_aliases a WHERE a.entity_type = 'attack-pattern'
                      AND a.alias_norm = entity_alias_norm(t.ttp_id))
 ORDER BY entity_alias_norm(t.ttp_id), t.prio, t.id
ON CONFLICT DO NOTHING;

INSERT INTO entity_aliases (entity_id, entity_type, alias, alias_norm, source)
SELECT id, type, external_id, entity_alias_norm(external_id), 'legacy'
  FROM entities WHERE type = 'attack-pattern' AND source = 'legacy'
ON CONFLICT DO NOTHING;

-- 4. Baris tautan -> entity_mentions. Dua ejaan yang kini satu entitas di subjek yang sama
-- runtuh jadi satu mention; yang dipakai baris lama dengan id terkecil (Ruling 8).
INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias)
SELECT DISTINCT ON (x.article_id, a.entity_id) x.article_id, a.entity_id,
       CASE WHEN x.source IN ('dictionary', 'llm', 'keyword', 'explicit', 'analyst')
            THEN x.source ELSE 'legacy' END,
       x.threat_actor
  FROM article_threat_actors x
  JOIN entity_aliases a ON a.entity_type = 'intrusion-set'
                       AND a.alias_norm = entity_alias_norm(x.threat_actor)
 ORDER BY x.article_id, a.entity_id, x.id;

INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias)
SELECT DISTINCT ON (x.article_id, a.entity_id) x.article_id, a.entity_id,
       CASE WHEN x.source IN ('dictionary', 'llm', 'keyword', 'explicit', 'analyst')
            THEN x.source ELSE 'legacy' END,
       x.name
  FROM article_malware x
  JOIN entity_aliases a ON a.entity_type = CASE WHEN x.kind = 'tool' THEN 'tool' ELSE 'malware' END
                       AND a.alias_norm = entity_alias_norm(x.name)
 ORDER BY x.article_id, a.entity_id, x.id;

INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias, evidence, extracted)
SELECT DISTINCT ON (x.article_id, a.entity_id) x.article_id, a.entity_id,
       CASE WHEN x.source IN ('dictionary', 'llm', 'keyword', 'explicit', 'analyst')
            THEN x.source ELSE 'legacy' END,
       x.ttp_id, x.evidence,
       nullif(jsonb_strip_nulls(jsonb_build_object('extracted_id', x.extracted_id,
                                                   'extracted_name', x.extracted_name)),
              '{}'::jsonb)
  FROM article_ttps x
  JOIN entity_aliases a ON a.entity_type = 'attack-pattern'
                       AND a.alias_norm = entity_alias_norm(x.ttp_id)
 ORDER BY x.article_id, a.entity_id, x.id;

INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias, extracted)
SELECT DISTINCT ON (x.article_id, a.entity_id) x.article_id, a.entity_id, 'legacy', x.cve_id,
       jsonb_build_object('in_title', x.in_title, 'first_seen_at', x.first_seen_at)
  FROM article_cves x
  JOIN entity_aliases a ON a.entity_type = 'vulnerability'
                       AND a.alias_norm = entity_alias_norm(x.cve_id)
 ORDER BY x.article_id, a.entity_id, x.cve_id;

INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias, role)
SELECT DISTINCT ON (x.article_id, e.id, x.role) x.article_id, e.id, 'legacy', x.country_code,
       x.role
  FROM article_countries x
  JOIN entities e ON e.type = 'location' AND e.external_id = upper(btrim(x.country_code))
 ORDER BY x.article_id, e.id, x.role, x.id;

INSERT INTO entity_mentions (article_id, entity_id, method, matched_alias)
SELECT DISTINCT ON (x.article_id, a.entity_id) x.article_id, a.entity_id,
       CASE WHEN x.source IN ('dictionary', 'llm', 'keyword', 'explicit', 'analyst')
            THEN x.source ELSE 'legacy' END,
       x.industry
  FROM article_industries x
  JOIN entity_aliases a ON a.entity_type = 'identity'
                       AND a.alias_norm = entity_alias_norm(x.industry)
 WHERE entity_alias_norm(x.industry) <> 'general'
 ORDER BY x.article_id, a.entity_id, x.id;

INSERT INTO entity_mentions (indicator_id, entity_id, method, matched_alias)
SELECT DISTINCT ON (x.indicator_id, a.entity_id) x.indicator_id, a.entity_id, 'legacy',
       x.threat_actor
  FROM indicator_threat_actors x
  JOIN entity_aliases a ON a.entity_type = 'intrusion-set'
                       AND a.alias_norm = entity_alias_norm(x.threat_actor)
 ORDER BY x.indicator_id, a.entity_id, x.id;

INSERT INTO entity_mentions (cve_tracker_id, entity_id, method, matched_alias)
SELECT DISTINCT ON (x.cve_tracker_id, a.entity_id) x.cve_tracker_id, a.entity_id, 'legacy',
       x.threat_actor
  FROM cve_threat_actors x
  JOIN entity_aliases a ON a.entity_type = 'intrusion-set'
                       AND a.alias_norm = entity_alias_norm(x.threat_actor)
 ORDER BY x.cve_tracker_id, a.entity_id, x.id;

INSERT INTO entity_mentions (cve_tracker_id, entity_id, method, matched_alias)
SELECT DISTINCT ON (x.cve_tracker_id, a.entity_id) x.cve_tracker_id, a.entity_id, 'legacy',
       x.ttp_id
  FROM cve_ttps x
  JOIN entity_aliases a ON a.entity_type = 'attack-pattern'
                       AND a.alias_norm = entity_alias_norm(x.ttp_id)
 ORDER BY x.cve_tracker_id, a.entity_id, x.id;

-- ransomware: grup targets korban, korban located-at negara (confidence 50, seen dari discovered)
INSERT INTO relationships (stix_id, relationship_type, source_entity_id, target_entity_id,
                           confidence, first_seen, last_seen, provenance)
SELECT 'relationship--' || gen_random_uuid(), 'targets', g.entity_id, v.entity_id, 50,
       min(r.discovered)::timestamp AT TIME ZONE 'UTC',
       max(r.discovered)::timestamp AT TIME ZONE 'UTC', 'ransomware'
  FROM ransomware_victims r
  JOIN entity_aliases g ON g.entity_type = 'intrusion-set'
                       AND g.alias_norm = entity_alias_norm(r.group_name)
  JOIN entity_aliases v ON v.entity_type = 'identity'
                       AND v.alias_norm = entity_alias_norm(left(r.victim, 300))
 GROUP BY g.entity_id, v.entity_id
 ORDER BY g.entity_id, v.entity_id
ON CONFLICT DO NOTHING;

INSERT INTO relationships (stix_id, relationship_type, source_entity_id, target_entity_id,
                           confidence, first_seen, last_seen, provenance)
SELECT 'relationship--' || gen_random_uuid(), 'located-at', v.entity_id, c.id, 50,
       min(r.discovered)::timestamp AT TIME ZONE 'UTC',
       max(r.discovered)::timestamp AT TIME ZONE 'UTC', 'ransomware'
  FROM ransomware_victims r
  JOIN entity_aliases v ON v.entity_type = 'identity'
                       AND v.alias_norm = entity_alias_norm(left(r.victim, 300))
  JOIN entities c ON c.type = 'location' AND c.external_id = upper(btrim(r.country_code))
 GROUP BY v.entity_id, c.id
 ORDER BY v.entity_id, c.id
ON CONFLICT DO NOTHING;

-- 5. watchlist, profil, whitelist
INSERT INTO entity_watches (client_id, entity_id, created_at)
SELECT DISTINCT ON (w.client_id, a.entity_id) w.client_id, a.entity_id, w.created_at
  FROM ta_watchlist w
  JOIN entity_aliases a ON a.entity_type = 'intrusion-set'
                       AND a.alias_norm = entity_alias_norm(w.name)
 ORDER BY w.client_id, a.entity_id, w.id;

-- dua profil yang kini satu entitas: yang paling baru dibuat dipakai
INSERT INTO entity_profiles (entity_id, profile, generated_at)
SELECT DISTINCT ON (a.entity_id) a.entity_id, p.profile, p.generated_at
  FROM ta_profiles p
  JOIN entity_aliases a ON a.entity_type = 'intrusion-set'
                       AND a.alias_norm = entity_alias_norm(p.actor_name)
 ORDER BY a.entity_id, p.generated_at DESC, p.id;

UPDATE entities e SET suppressed = true
  FROM ta_whitelist w
  JOIN entity_aliases a ON a.entity_type = 'intrusion-set'
                       AND a.alias_norm = entity_alias_norm(w.name)
 WHERE e.id = a.entity_id;

-- 6. first_seen/last_seen dari mention artikel (tanggal terbit posted_on, cadangan created_at)
UPDATE entities e SET first_seen = s.f, last_seen = s.l
  FROM (SELECT m.entity_id,
               min(coalesce(ar.posted_on::timestamp AT TIME ZONE 'UTC', ar.created_at)) AS f,
               max(coalesce(ar.posted_on::timestamp AT TIME ZONE 'UTC', ar.created_at)) AS l
          FROM entity_mentions m JOIN articles ar ON ar.id = m.article_id
         GROUP BY m.entity_id) s
 WHERE e.id = s.entity_id;

-- 7. jam feed: entitas/relasi baru sudah clock_timestamp() >= created_at; story dari last_seen_at
UPDATE stories SET feed_changed_at = greatest(created_at, last_seen_at);

DROP TABLE _bf_names, _bf_sectors, _bf_sector_labels, _bf_countries;
