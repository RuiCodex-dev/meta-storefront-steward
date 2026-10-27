"""40 SYNTHETIC reviews in 8 languages with planted personal data. No real person or review.

Each entry lists exactly what was planted. The scrubber must remove every planted e-mail, phone and
order id, at least 95% of planted names, and must leave the CONTROL texts byte-identical.
Controls are deliberately hard: version numbers, scores, prices, dates and capitalised game words.
"""

PLANTED = [
    # English
    dict(lang="en", author="Jonathan Pierce", text="Lost all progress after update. Mail me at jon.pierce77@example.com please!",
         planted={"EMAIL": ["jon.pierce77@example.com"]}),
    dict(lang="en", author="Sarah K", text="My name is Sarah Klein and I paid twice, order GPA.3341-2290-1187-55621 never arrived",
         planted={"NAME": ["Sarah Klein"], "ORDER_ID": ["GPA.3341-2290-1187-55621"]}),
    dict(lang="en", author="mike_t", text="Call me on +1 415 555 0132 if you need logs. Crashes on level 12.",
         planted={"PHONE": ["+1 415 555 0132"]}),
    dict(lang="en", author="Emily Rhodes", text="Emily here. The ads are too long, Emily Rhodes is unsubscribing.",
         planted={"NAME": ["Emily Rhodes", "Emily"]}),
    dict(lang="en", author="A Google user", text="Charged me, receipt MKX7Q2P9LZ, refund please. Twitter @gamerdad_88",
         planted={"ORDER_ID": ["MKX7Q2P9LZ"], "HANDLE": ["@gamerdad_88"]}),
    # Dutch
    dict(lang="nl", author="Pieter de Vries", text="Mijn naam is Pieter de Vries, bel me op 06 12 34 56 78 aub.",
         planted={"NAME": ["Pieter"], "PHONE": ["06 12 34 56 78"]}),
    dict(lang="nl", author="Lotte", text="Bestelling nummer GPA.1123-4455-6677-88990 is niet geleverd. lotte.b@example.com",
         planted={"ORDER_ID": ["GPA.1123-4455-6677-88990"], "EMAIL": ["lotte.b@example.com"]}),
    dict(lang="nl", author="Jan Peeters", text="Jan Peeters hier: na de update 2.3.1 start het spel niet meer.",
         planted={"NAME": ["Jan Peeters"]}),
    dict(lang="nl", author="Sanne", text="Ik heet Sanne en mijn IBAN is BE68 5390 0754 7034, waar is mijn terugbetaling?",
         planted={"NAME": ["Sanne"], "IBAN": ["BE68 5390 0754 7034"]}),
    dict(lang="nl", author="Kevin Maes", text="Stuur een mail naar kevin.maes@example.com of www.kevinmaes.be/contact?id=7",
         planted={"EMAIL": ["kevin.maes@example.com"], "URL": ["www.kevinmaes.be/contact?id=7"]}),
    # French
    dict(lang="fr", author="Camille Durand", text="Je m'appelle Camille Durand, le jeu plante au niveau 40. camille.d@example.com",
         planted={"NAME": ["Camille Durand"], "EMAIL": ["camille.d@example.com"]}),
    dict(lang="fr", author="Luc", text="Appelez-moi au +32 470 12 34 56, commande GPA.9988-7766-5544-33221 non reçue",
         planted={"PHONE": ["+32 470 12 34 56"], "ORDER_ID": ["GPA.9988-7766-5544-33221"]}),
    dict(lang="fr", author="Amélie Laurent", text="Amélie Laurent : trop de publicités depuis la version 3.0",
         planted={"NAME": ["Amélie Laurent"]}),
    dict(lang="fr", author="Hugo", text="Mon nom est Hugo Martin et je veux un remboursement, commande numéro 4A7B9C2D1E",
         planted={"NAME": ["Hugo Martin"], "ORDER_ID": ["4A7B9C2D1E"]}),
    dict(lang="fr", author="Inès B", text="Contact : ines.b+jeux@example.com ou 01 42 68 53 00",
         planted={"EMAIL": ["ines.b+jeux@example.com"], "PHONE": ["01 42 68 53 00"]}),
    # German
    dict(lang="de", author="Lukas Schmidt", text="Ich heiße Lukas Schmidt. Bestellung GPA.5544-3322-1100-99887 fehlt.",
         planted={"NAME": ["Lukas Schmidt"], "ORDER_ID": ["GPA.5544-3322-1100-99887"]}),
    dict(lang="de", author="Anna", text="Schreibt mir: anna.mueller@example.com, Telefon 0151 2345 6789",
         planted={"EMAIL": ["anna.mueller@example.com"], "PHONE": ["0151 2345 6789"]}),
    dict(lang="de", author="Felix Wagner", text="Felix Wagner sagt: Absturz nach Werbung, Version 1.4.2",
         planted={"NAME": ["Felix Wagner"]}),
    dict(lang="de", author="Marie", text="Mein Name ist Marie Becker, Konto DE89 3704 0044 0532 0130 00 für Erstattung",
         planted={"NAME": ["Marie Becker"], "IBAN": ["DE89 3704 0044 0532 0130 00"]}),
    dict(lang="de", author="jonas.k", text="Kreditkarte 4111 1111 1111 1111 wurde zweimal belastet!",
         planted={"NUMBER": ["4111 1111 1111 1111"]}),
    # Turkish
    dict(lang="tr", author="Ahmet Yılmaz", text="Benim adım Ahmet Yılmaz, oyun açılmıyor. ahmet.yilmaz@example.com",
         planted={"NAME": ["Ahmet Yılmaz"], "EMAIL": ["ahmet.yilmaz@example.com"]}),
    dict(lang="tr", author="Zeynep", text="Beni arayın +90 532 123 45 67, sipariş GPA.2211-3344-5566-77889 gelmedi",
         planted={"PHONE": ["+90 532 123 45 67"], "ORDER_ID": ["GPA.2211-3344-5566-77889"]}),
    dict(lang="tr", author="Mehmet Demir", text="Mehmet Demir: reklamlar çok fazla, 2.0 sürümünden beri",
         planted={"NAME": ["Mehmet Demir"]}),
    dict(lang="tr", author="Elif", text="Instagram @elif.oyunda takip edin, iade istiyorum",
         planted={"HANDLE": ["@elif.oyunda"]}),
    dict(lang="tr", author="Burak Kaya", text="Burak Kaya olarak yazıyorum, seviye 25 te donuyor",
         planted={"NAME": ["Burak Kaya"]}),
    # Spanish
    dict(lang="es", author="Lucía García", text="Me llamo Lucía García y no puedo iniciar sesión. lucia.garcia@example.com",
         planted={"NAME": ["Lucía García"], "EMAIL": ["lucia.garcia@example.com"]}),
    dict(lang="es", author="Diego", text="Pedido GPA.6677-8899-0011-22334 cobrado dos veces, llamar al +34 612 345 678",
         planted={"ORDER_ID": ["GPA.6677-8899-0011-22334"], "PHONE": ["+34 612 345 678"]}),
    dict(lang="es", author="Carmen López", text="Carmen López: el juego se cierra solo",
         planted={"NAME": ["Carmen López"]}),
    dict(lang="es", author="Pablo", text="Mi nombre es Pablo Ruiz, escribidme a pablo.ruiz@example.com",
         planted={"NAME": ["Pablo Ruiz"], "EMAIL": ["pablo.ruiz@example.com"]}),
    dict(lang="es", author="Sofía", text="Visita https://sofia-blog.example.com/review?user=sofia123 para ver el error",
         planted={"URL": ["https://sofia-blog.example.com/review?user=sofia123"]}),
    # Italian
    dict(lang="it", author="Giulia Rossi", text="Mi chiamo Giulia Rossi, ordine GPA.4455-6677-8899-00112 mai arrivato",
         planted={"NAME": ["Giulia Rossi"], "ORDER_ID": ["GPA.4455-6677-8899-00112"]}),
    dict(lang="it", author="Marco", text="Scrivetemi: marco.bianchi@example.com, cell +39 347 123 4567",
         planted={"EMAIL": ["marco.bianchi@example.com"], "PHONE": ["+39 347 123 4567"]}),
    dict(lang="it", author="Francesca Conti", text="Francesca Conti: troppa pubblicità dopo l'aggiornamento",
         planted={"NAME": ["Francesca Conti"]}),
    dict(lang="it", author="Luca", text="IBAN IT60 X054 2811 1010 0000 0123 456 per il rimborso",
         planted={"IBAN": ["IT60 X054 2811 1010 0000 0123 456"]}),
    dict(lang="it", author="Alessandro Greco", text="Alessandro Greco qui, il livello 9 non si carica",
         planted={"NAME": ["Alessandro Greco"]}),
    # Portuguese
    dict(lang="pt", author="João Silva", text="Meu nome é João Silva, comprei e não recebi. joao.silva@example.com",
         planted={"NAME": ["João Silva"], "EMAIL": ["joao.silva@example.com"]}),
    dict(lang="pt", author="Ana", text="Liguem para +55 11 91234 5678, pedido GPA.7788-9900-1122-33445",
         planted={"PHONE": ["+55 11 91234 5678"], "ORDER_ID": ["GPA.7788-9900-1122-33445"]}),
    dict(lang="pt", author="Beatriz Costa", text="Beatriz Costa: o jogo trava na versão 5.1",
         planted={"NAME": ["Beatriz Costa"]}),
    dict(lang="pt", author="Rafael", text="Me sigam @rafa_games no YouTube, bug no nível 3",
         planted={"HANDLE": ["@rafa_games"]}),
    dict(lang="pt", author="Mariana Alves", text="Mariana Alves aqui, transação MKA9P3Q7R2 cobrada duas vezes",
         planted={"NAME": ["Mariana Alves"], "ORDER_ID": ["MKA9P3Q7R2"]}),
]

# Must come out byte-identical: numbers, versions, prices, dates and capitalised game words are not PII.
CONTROLS = [
    "Great game! Reached level 1000 and 2500000 coins. Version 2.3.1 fixed the lag. 5 stars.",
    "Na update 3.0.12 werkt alles weer. Prijs €4,99 is eerlijk. Level 45 is lastig.",
    "Le niveau 12 est trop dur depuis le 14/10/2026. Les Pierres Magiques sont géniales.",
    "Seit Version 1.4.2 stürzt es nicht mehr ab. Der Drache auf Stufe 30 ist cool.",
    "Oyun çok güzel ama 25. seviyede reklam çok. Sürüm 2.0.1 daha iyi.",
    "Me encanta, nivel 999, puntuación 123456. El Rey Dragón es difícil.",
]
