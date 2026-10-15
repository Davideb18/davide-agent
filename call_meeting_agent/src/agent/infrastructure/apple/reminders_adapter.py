"""
reminders_adapter.py — Adattatore nativo macOS per Apple Reminders (Promemoria).
Implementa RemindersServicePort con interazione tramite osascript (AppleScript) e graceful fallback.
"""
import sys
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
        Crea automaticamente la lista dedicata se non esiste.
        """
        if not task_items:
            return False, "Nessun compito da esportare."

        if sys.platform != "darwin":
            msg = "Apple Reminders è supportato nativamente solo su macOS."
            logger.info(msg)
            return False, msg

        clean_list_name = list_name.replace('"', '\\"').strip()
        
        # Genera i comandi di creazione promemoria in AppleScript
        reminder_creation_lines = []
        for item in task_items:
            # Rimuove newline e caratteri di controllo che spezzerebbero il comando AppleScript
            sanitized = item.replace("\r", " ").replace("\n", " ").strip()
            cleaned_item = sanitized.replace("\\", "\\\\").replace('"', '\\"')
            if cleaned_item:
                reminder_creation_lines.append(
                    f'make new reminder with properties {{name:"{cleaned_item}"}}'
                )

        if not reminder_creation_lines:
            return False, "Tutti i compiti forniti sono vuoti."

        reminders_body = "\n        ".join(reminder_creation_lines)

        script = f'''
        tell application "Reminders"
            if not (exists list "{clean_list_name}") then
                make new list with properties {{name:"{clean_list_name}"}}
            end if
            set targetList to list "{clean_list_name}"
            tell targetList
                {reminders_body}
            end tell
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode == 0:
                count = len(reminder_creation_lines)
                return True, f"{count} promemoria sincronizzati con successo nella lista '{list_name}' di Apple Reminders."
            
            stderr = result.stderr.strip() if result.stderr else "Errore sconosciuto durante l'esecuzione di AppleScript."
            logger.warning(f"Errore osascript Reminders: {stderr}")
            if "not allowed" in stderr.lower() or "permission" in stderr.lower() or "-1743" in stderr:
                return False, "Permesso negato: concedi ad Aria l'accesso all'app Promemoria in 'Impostazioni di Sistema > Privacy e Sicurezza > Automazione'."
            return False, f"Impossibile esportare su Promemoria: {stderr}"

        except subprocess.TimeoutExpired:
            logger.error("Timeout durante l'interazione con Apple Reminders via osascript.")
            return False, "Timeout: l'app Promemoria di Apple non ha risposto entro 15 secondi."
        except Exception as e:
            logger.error(f"Eccezione inattesa in AppleRemindersAdapter: {e}")
            return False, f"Errore di sistema Apple Reminders: {e}"
