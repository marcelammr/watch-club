import { createRoot } from "react-dom/client";
import { DirectionProvider } from "@/components/ui/direction";
import { CommandPalette } from "./command-palette";
import { mountColorPickers, setColorPickerHex } from "./color-picker";
import { mountEmojiPickers } from "./emoji-picker";
import { mountLoginForm } from "./login-form";
import { mountUserAvatars, remountUserAvatars } from "./user-avatar";

declare global {
  interface Window {
    WatchClub?: {
      remountUserAvatars: typeof remountUserAvatars;
      setColorPickerHex: typeof setColorPickerHex;
    };
  }
}

window.WatchClub = { remountUserAvatars, setColorPickerHex };

const commandRoot = document.getElementById("command-root");
if (commandRoot) {
  createRoot(commandRoot).render(
    <DirectionProvider direction="ltr">
      <CommandPalette />
    </DirectionProvider>
  );
}

mountUserAvatars();
mountLoginForm();
mountEmojiPickers();
mountColorPickers();
