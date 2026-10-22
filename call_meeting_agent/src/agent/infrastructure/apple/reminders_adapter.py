"""
reminders_adapter.py — Adattatore nativo macOS per Apple Reminders (Promemoria).
Implementa RemindersServicePort con interazione tramite osascript (AppleScript) e graceful fallback.
"""
import sys
import asyncio
import subprocess
import logging
from typing import List, Tuple

from ...domain.ports import RemindersServicePort

logger = logging.getLogger(__name__)


class AppleRemindersAdapter:
    """Implementazione nativa macOS di RemindersServicePort tramite AppleScript."""

    async def export_tasks(
        self, task_items: List[str], list_name: str = "Aria Tasks"
    ) -> Tuple[bool, str]:
        """
        Esporta una lista di compiti direttamente nell'app Promemoria (Reminders) di Apple.
        Crea automaticamente la lista dedicata se non esiste. Esecuzione asincrona non-bloccante.
        """
        if not task_items:
            return False, "Nessun compito da esportare."

        if sys.platform != "darwin":
            msg = "Apple Reminders è supportato nativamente solo su macOS."
            logger.info(msg)
            return False, msg

        clean_list_name = list_name.replace('"', '\\"').strip()

        # Sanificazione e formattazione lista elementi per AppleScript
        sanitized_items = []
        for item in task_items:
            sanitized = item.replace("\r", " ").replace("\n", " ").strip()
            cleaned_item = sanitized.replace("\\", "\\\\").replace('"', '\\"')
            if cleaned_item:
                sanitized_items.append(f'"{cleaned_item}"')

        if not sanitized_items:
            return False, "Tutti i compiti forniti sono vuoti."

        items_array_str = ", ".join(sanitized_items)

        # Script AppleScript robusto e affidabile: crea ciascun promemoria nella lista di default (o lista indicata)
        # Assicura corretta coercizione a testo e attende l'inserimento reale
        script = f'''
        tell application "Reminders"
            set targetList to default list
            if "{clean_list_name}" is not "" and "{clean_list_name}" is not "Promemoria" and "{clean_list_name}" is not "default" then
                if not (exists list "{clean_list_name}") then
                    make new list with properties {{name:"{clean_list_name}"}}
                end if
                set targetList to list "{clean_list_name}"
            end if
            set listDisplayName to name of targetList
            repeat with itemText in {{{items_array_str}}}
                make new reminder at targetList with properties {{name:(itemText as text)}}
            end repeat
            return listDisplayName
        end tell
        '''

        def _run_script():
            # Assicura avvio in background senza rubare il focus all'utente
            try:
                subprocess.run(["open", "-g", "-a", "Reminders"], capture_output=True, timeout=2)
            except Exception:
                pass

            return subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=12,
            )

        try:
            result = await asyncio.to_thread(_run_script)

            if result.returncode == 0:
                count = len(sanitized_items)
                actual_list = (result.stdout or "").strip() or list_name
                return True, f"{count} promemoria salvati con successo nella lista '{actual_list}' di Apple Reminders."

            stderr = result.stderr.strip() if result.stderr else "Errore sconosciuto durante l'esecuzione di AppleScript."
            logger.warning(f"Errore osascript Reminders: {stderr}")
            if "not allowed" in stderr.lower() or "permission" in stderr.lower() or "-1743" in stderr:
                return False, "Permesso negato: concedi ad Aria l'accesso all'app Promemoria in 'Impostazioni di Sistema > Privacy e Sicurezza > Automazione'."
            return False, f"Impossibile esportare su Promemoria: {stderr}"

        except subprocess.TimeoutExpired:
            logger.error("Timeout durante l'interazione con Apple Reminders via osascript.")
            return False, "Timeout: l'app Promemoria di Apple non ha risposto entro 12 secondi."
        except Exception as e:
            logger.error(f"Eccezione inattesa in AppleRemindersAdapter: {e}")
            return False, f"Errore di sistema Apple Reminders: {e}"
