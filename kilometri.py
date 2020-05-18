import collections
import telegram
import time

import db

extract_nick = lambda update: update.message.from_user["username"]
extract_uid = lambda update: update.message.from_user["id"]
poista_skandit = lambda s: s.replace("ä", "a").replace("Ä", "A").replace("ö", "o").replace("Ö", "O")

def dbgShowException(func):
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as e:
            print("Exception: %s" % repr(e))
    return wrapper

class Kilometri:
    Laji = collections.namedtuple("Laji", ("monikko", "partisiippi", "getter", "getTop", "taulukko", "kerroin"))

    lajit = {
        "kavely": Laji("kävelijät", "kävellyt", db.getKavelyt, db.getTopKavelyt, "Kavelyt", 1),
        "juoksu": Laji("juoksijat", "juossut", db.getJuoksut, db.getTopJuoksut, "Juoksut", 3),
        "pyoraily": Laji("pyöräilijät", "pyöräillyt", db.getPyorailyt, db.getTopPyorailyt, "Pyorailyt", 0.5),
    }

    def __init__(self):
        self.commands = {
            'pisteet': self.pisteetHandler,
            'kmstats': self.statsHandler,
            'kmhelp': self.helpHandler,
        }

        for lajinnimi, laji in self.lajit.items():
            listauskomento = poista_skandit(laji.monikko)

            lisaa, listaa = self.__genLajiHandlerit(lajinnimi)
            self.commands[lajinnimi] = lisaa
            self.commands[listauskomento] = listaa

        self.helptext = "Komennot, kokeile ilman parametria jos et ole varma:\n\n" + "\n".join(
            map(lambda s: "/%s" % s, self.commands.keys()))

    def getCommands(self):
        return self.commands

    def __genLajiHandlerit(self, lajinnimi):
        def urh(*args, **kwargs):
            self.__urheilinHandler(lajinnimi, *args, **kwargs)

        def get(*args, **kwargs):
            self.__getStatHandler(lajinnimi, *args, **kwargs)

        return (urh, get)

    def __userFromUid(self, bot, update, uid):
        chat_id = update.message.chat_id
        return bot.get_chat_member(chat_id, uid).user

    def __nameFromUid(self, bot, update, uid):
        user = self.__userFromUid(bot, update, uid)
        if (user.username is None):
            return "%s %s" % (str(user.first_name), str(user.last_name))
        else:
            return user.username

    def __parsiAikaLkm(self, args):
        aikasuureet = {
            "s":   1,
            "sek": 1,
            "m":   60,
            "min": 60,
            "h":   60 * 60,
            "pv":  60 * 60 * 24,
            "d":   60 * 60 * 24,
            "kk":  60 * 60 * 24 * 30,
            "mo":  60 * 60 * 24 * 30,
            "v":   60 * 60 * 24 * 30 * 365,
            "y":   60 * 60 * 24 * 30 * 365,
        }

        aika = 3 * aikasuureet["kk"]
        aikanimi = "3kk"
        lkm = 10

        for arg in args:
            try:
                lkm = int(arg)
                continue
            except ValueError:
                pass

            for lyhenne, kerroin in aikasuureet.items():
                if (arg.endswith(lyhenne)):
                    try:
                        aika = float(arg.rstrip(lyhenne)) * kerroin
                        aikanimi = arg
                        break
                    except ValueError:
                        pass
            else:
                raise ValueError("Unrecognized '%s' in args" % arg)

        return (aika, aikanimi, lkm)

    def __urheilinHandler(self, lajinnimi, bot, update, args):
        def printUsage():
            usage = "Usage: /%s <km>" % lajinnimi
            bot.sendMessage(chat_id=update.message.chat_id, text=usage)

        if (len(args) != 1):
            printUsage()
            return

        laji = self.lajit[lajinnimi]
        uid = extract_uid(update)
        try:
            km = float(args[0].rstrip("km"))
        except ValueError:
            printUsage()
            return

        now = int(time.time())
        db.addUrheilu(uid, km, now, laji.taulukko)
        bot.sendMessage(chat_id=update.message.chat_id,
            text="Lisätään %s %.1f km" % (lajinnimi, km))

    @dbgShowException
    def __getStatHandler(self, lajinnimi, bot, update, args):
        def printUsage(komento):
            usage = "Usage: /%s [lkm] [ajalta]" % komento
            bot.sendMessage(chat_id=update.message.chat_id, text=usage)

        laji = self.lajit[lajinnimi]
        try:
            aika, aikanimi, lkm = self.__parsiAikaLkm(args)
        except ValueError:
            printUsage(poista_skandit(laji.monikko))
            return

        top_suoritukset = laji.getTop(time.time() - aika, lkm)

        lista = "\n".join("%s: %.1f km" %
                (self.__nameFromUid(bot, update, uid), km)
            for uid, km in top_suoritukset)

        bot.sendMessage(chat_id=update.message.chat_id,
            text="Top %i %s viimeisen %s aikana:\n\n%s" %
                (lkm, laji.monikko, aikanimi, lista))



    def pisteetHandler(self, bot, update, args=tuple()):
        def usage():
            bot.sendMessage(chat_id=update.message.chat_id,
                text="Usage: /pisteet [ajalta]")
        try:
            aika, aikanimi, lkm = self.__parsiAikaLkm(args)
        except ValueError:
            usage()
            return

        alkaen = time.time() - aika
        score_strs = []
        mults_tables = ((laji.kerroin, laji.taulukko) for laji in self.lajit.values())
        pisteet = db.getPisteet(mults_tables, alkaen, lkm)

        for uid, score in pisteet:
            name = self.__nameFromUid(bot, update, uid)
            score_strs.append("%s: %.1f pistettä" % (name, score))

        msg = "Top %i pisteet viimeisen %s aikana:\n\n%s" % (
            lkm, aikanimi, "\n".join(score_strs))

        bot.sendMessage(chat_id=update.message.chat_id, text=msg)

    def statsHandler(self, bot, update, args=tuple()):
        def usage():
            bot.sendMessage(chat_id=update.message.chat_id,
                text="Usage: /kmstats [ajalta]")

        try:
            aika, aikanimi, _ = self.__parsiAikaLkm(args)
        except ValueError:
            usage()
            return

        alkaen = time.time() - aika
        uid = extract_uid(update)
        name = self.__nameFromUid(bot, update, uid)

        stats = []
        for lajinnimi, laji in self.lajit.items():
            km = laji.getter(uid, alkaen)
            if (km is None):
                km = 0
            print("%s: %.1f" % (lajinnimi, km))
            stats.append((laji, km))

        score = sum(laji.kerroin * km for laji, km in stats)
        stat_str = "Viimeisen %s aikana %.1f pistettä\n\n" % (aikanimi, score)

        stat_str += ", ".join(
            "%s %.1f km" % (laji.partisiippi, km)
            for laji, km in stats)

        bot.sendMessage(chat_id=update.message.chat_id,
                        text="%s: %s" % (name, stat_str))

    def helpHandler(self, bot, update, args=tuple()):
        bot.sendMessage(chat_id=update.message.chat_id, text=self.helptext)
