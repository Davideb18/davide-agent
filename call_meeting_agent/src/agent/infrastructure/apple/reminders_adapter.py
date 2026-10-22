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

        # Script AppleScript anti-duplicati: verifica promemoria esistenti prima di crearne di nuovi
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
            set createdCount to 0
            repeat with itemText in {{{items_array_str}}}
                set tName to (itemText as text)
                set existingReminders to (every reminder of targetList whose name is tName and completed is false)
                if (count of existingReminders) is 0 then
                    make new reminder at targetList with properties {{name:tName}}
                    set createdCount to createdCount + 1
                end if
            end repeat
            return (listDisplayName & "|" & (createdCount as text))
        end tell
        '''

        def _run_script():
            import time
            last_res = None
            for attempt in range(2):
                try:
                    subprocess.run(["open", "-g", "-a", "Reminders"], capture_output=True, timeout=3)
                    if attempt == 0:
                        time.sleep(0.3)
                except Exception:
                    pass

                try:
                    res = subprocess.run(
                        ["osascript", "-e", 'tell application "Reminders" to launch', "-e", script],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if res.returncode == 0:
                        return res
                    last_res = res
                    if "-600" in (res.stderr or "") and attempt == 0:
                        time.sleep(0.8)
                        continue
                    return res
                except subprocess.TimeoutExpired:
                    if attempt == 0:
                        time.sleep(0.6)
                        continue
                    raise
            return last_res or subprocess.CompletedProcess(args=[], returncode=1, stderr="Operazione non completata.")

        try:
            result = await asyncio.to_thread(_run_script)

            if result.returncode == 0:
                stdout_str = (result.stdout or "").strip()
                actual_list = list_name
                created_count = len(sanitized_items)
                if "|" in stdout_str:
                    parts = stdout_str.split("|", 1)
                    actual_list = parts[0].strip() or list_name
                    try:
                        created_count = int(parts[1].strip())
                    except Exception:
                        created_count = len(sanitized_items)
                else:
                    actual_list = stdout_str or list_name

                tot_items = len(sanitized_items)
                if created_count == 0:
                    return True, f"Tutti i {tot_items} compiti sono già sincronizzati in Promemoria macOS (zero duplicati)."
                elif created_count < tot_items:
                    return True, f"{created_count} nuovi compiti aggiunti a Promemoria macOS (totale {tot_items} allineati)."
                else:
                    return True, f"{tot_items} promemoria salvati con successo nella lista '{actual_list}' di Apple Reminders."

            stderr = result.stderr.strip() if result.stderr else "Errore sconosciuto durante l'esecuzione di AppleScript."
            logger.warning(f"Errore osascript Reminders: {stderr}")
            if "not allowed" in stderr.lower() or "permission" in stderr.lower() or "-1743" in stderr:
                return False, "Sincronizzazione Apple Promemoria non autorizzata da macOS (Automazione non abilitata). I compiti sono comunque archiviati al sicuro in Tasks.md e nel database locale."
            return False, f"Impossibile esportare su Promemoria: {stderr}. I compiti restano al sicuro in Tasks.md."

        except subprocess.TimeoutExpired:
            logger.warning("Timeout (10s) durante l'interazione con Apple Reminders via osascript.")
            return False, "L'app Promemoria di Apple non ha risposto entro 10 secondi (richiede autorizzazione macOS o l'app non è aperta). I compiti sono comunque archiviati e custoditi al sicuro in Tasks.md."
        except Exception as e:
            logger.error(f"Eccezione inattesa in AppleRemindersAdapter: {e}")
            return False, f"Errore Apple Reminders: {e}. I compiti restano al sicuro in Tasks.md."
