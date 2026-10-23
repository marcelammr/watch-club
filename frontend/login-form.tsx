import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { DirectionProvider } from "@/components/ui/direction";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function EyeIcon({ crossed }: { crossed: boolean }) {
  if (crossed) {
    return (
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M3 3l18 18" />
        <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8" />
        <path d="M9.9 5.1A9.8 9.8 0 0 1 12 5c5 0 9 4.5 10 7-.3.8-1 2-2.1 3.3" />
        <path d="M6.1 6.1C4.2 7.6 2.7 9.5 2 12c1 2.5 5 7 10 7 1.4 0 2.7-.3 3.9-.8" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function PasswordField({
  id,
  name,
  autoComplete,
}: {
  id: string;
  name: string;
  autoComplete?: string;
}) {
  const [visible, setVisible] = useState(false);
  const label = visible ? "Ocultar senha" : "Mostrar senha";
  return (
    <div className="password-field">
      <Input
        id={id}
        name={name}
        type={visible ? "text" : "password"}
        required
        minLength={4}
        autoComplete={autoComplete}
      />
      <button
        type="button"
        className="password-toggle"
        aria-label={label}
        aria-pressed={visible}
        aria-controls={id}
        onClick={() => setVisible((open) => !open)}
      >
        <EyeIcon crossed={visible} />
      </button>
    </div>
  );
}

type AuthMode = "login" | "register" | "forgot" | "reset";

type AuthProps = {
  mode: AuthMode;
  error: string;
  ok?: string;
  suggestions: string[];
  form: {
    name?: string;
    username?: string;
    email?: string;
    invite_code?: string;
  };
  dev_code?: string | null;
  invite_required?: boolean;
};

function UsernameSuggestions({
  items,
  onPick,
}: {
  items: string[];
  onPick: (value: string) => void;
}) {
  if (!items.length) {
    return null;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <Button
          key={item}
          type="button"
          variant="secondary"
          size="sm"
          className="rounded-full"
          onClick={() => onPick(item)}
        >
          {item}
        </Button>
      ))}
    </div>
  );
}

export function LoginForm({ mode, error, ok, suggestions, form, dev_code, invite_required = false }: AuthProps) {
  const isLogin = mode === "login";
  const isRegister = mode === "register";
  const isForgot = mode === "forgot";
  const isReset = mode === "reset";
  const [username, setUsername] = useState(form.username || "");
  const [liveMessage, setLiveMessage] = useState("");
  const [liveSuggestions, setLiveSuggestions] = useState<string[]>([]);

  useEffect(() => {
    if (!isRegister || username.trim().length < 3) {
      setLiveMessage("");
      setLiveSuggestions([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      const data = await fetch(`/api/username?q=${encodeURIComponent(username.trim())}`).then(
        (response) => response.json()
      );
      if (data.available) {
        setLiveMessage("Nome disponível");
        setLiveSuggestions([]);
      } else {
        setLiveMessage("");
        setLiveSuggestions(data.suggestions || []);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [isRegister, username]);

  const title = isForgot ? "Recuperar senha" : isReset ? "Redefinir senha" : isLogin ? "Entrar" : "Criar conta";

  return (
    <DirectionProvider direction="ltr">
      <div className="flex flex-col gap-6" dir="ltr">
        <Card>
          <CardHeader>
            <CardTitle className="text-2xl">{title}</CardTitle>
            <CardDescription>
              {isForgot
                ? "Informe o e-mail da conta. Se ele existir, enviamos um código para redefinir a senha."
                : isReset
                  ? "Digite o código recebido por e-mail e escolha uma nova senha."
                  : isLogin
                    ? "Digite seu e-mail abaixo para entrar na sua conta."
                    : "Preencha os dados abaixo para criar sua conta no Watch Club."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {ok ? <p className="mb-4 text-sm text-chart-2">{ok}</p> : null}
            {error ? <p className="mb-4 text-sm text-destructive">{error}</p> : null}
            {isRegister && suggestions.length ? (
              <div className="mb-4 grid gap-2">
                <p className="text-sm text-muted-foreground">Variações disponíveis:</p>
                <UsernameSuggestions items={suggestions} onPick={setUsername} />
              </div>
            ) : null}
            {isReset && dev_code ? (
              <p className="mb-4 text-sm text-chart-2">Modo local: seu código é {dev_code}</p>
            ) : null}
            <form method="post" className="flex flex-col gap-6">
              <div className="flex flex-col gap-6">
                {isRegister ? (
                  <>
                    <div className="grid gap-2">
                      <Label htmlFor="name">Nome</Label>
                      <Input id="name" name="name" required maxLength={80} defaultValue={form.name || ""} placeholder="Seu nome" />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="username">Nickname</Label>
                      <Input
                        id="username"
                        name="username"
                        required
                        minLength={3}
                        maxLength={30}
                        value={username}
                        onChange={(event) => setUsername(event.target.value)}
                        placeholder="ex: marcela_tv"
                      />
                      <p className="text-sm text-muted-foreground">
                        Único no site. Letras, números e _. Só pode ser alterado a cada 14 dias.
                      </p>
                      {liveMessage ? <p className="text-sm text-chart-2">{liveMessage}</p> : null}
                      <UsernameSuggestions items={liveSuggestions} onPick={setUsername} />
                    </div>
                    {invite_required ? (
                      <div className="grid gap-2">
                        <Label htmlFor="invite_code">Convite</Label>
                        <Input
                          id="invite_code"
                          name="invite_code"
                          required
                          maxLength={32}
                          defaultValue={form.invite_code || ""}
                          autoComplete="off"
                          spellCheck={false}
                          placeholder="WC-XXXX-XXXX-XXXX-X"
                        />
                        <p className="text-sm text-muted-foreground">Informe o código que você recebeu para criar a conta.</p>
                      </div>
                    ) : null}
                  </>
                ) : null}
                {isLogin || isRegister || isForgot ? (
                  <div className="grid gap-2">
                    <Label htmlFor="email">E-mail</Label>
                    <Input
                      id="email"
                      name="email"
                      type="email"
                      required
                      defaultValue={form.email || ""}
                      placeholder="voce@email.com"
                      autoComplete="email"
                    />
                  </div>
                ) : null}
                {isReset ? (
                  <>
                    <div className="grid gap-2">
                      <Label htmlFor="code">Código</Label>
                      <Input
                        id="code"
                        name="code"
                        required
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={6}
                        pattern="[0-9]{6}"
                        placeholder="000000"
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="new_password">Nova senha</Label>
                      <PasswordField id="new_password" name="new_password" autoComplete="new-password" />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="confirm_password">Confirmar nova senha</Label>
                      <PasswordField id="confirm_password" name="confirm_password" autoComplete="new-password" />
                    </div>
                  </>
                ) : null}
                {isLogin || isRegister ? (
                  <div className="grid gap-2">
                    <div className="flex items-center">
                      <Label htmlFor="password">Senha</Label>
                      {isLogin ? (
                        <a href="/recuperar-senha" className="ms-auto text-sm underline-offset-4 hover:underline">
                          Esqueceu a senha?
                        </a>
                      ) : null}
                    </div>
                    <PasswordField
                      id="password"
                      name="password"
                      autoComplete={isLogin ? "current-password" : "new-password"}
                    />
                  </div>
                ) : null}
                <button className="btn btn-primary w-full" type="submit">
                  {isForgot ? "Enviar código" : isReset ? "Redefinir senha" : isLogin ? "Entrar" : "Cadastrar"}
                </button>
                {isReset ? (
                  <Button variant="outline" className="w-full" asChild>
                    <a href="/recuperar-senha">Enviar outro código</a>
                  </Button>
                ) : null}
                {isLogin || (isRegister && !invite_required) ? (
                  <>
                    <div className="relative text-center text-sm after:absolute after:inset-0 after:top-1/2 after:z-0 after:flex after:items-center after:border-t after:border-border">
                      <span className="relative z-10 bg-card px-2 text-muted-foreground">ou continue com</span>
                    </div>
                    <Button variant="outline" className="w-full bg-white text-black hover:bg-white/90 hover:text-black" asChild>
                      <a href="/auth/google">Continuar com Gmail</a>
                    </Button>
                    <Button
                      variant="outline"
                      className="w-full border-transparent bg-[#1877f2] text-white hover:bg-[#1877f2]/90 hover:text-white"
                      asChild
                    >
                      <a href="/auth/facebook">Continuar com Facebook</a>
                    </Button>
                  </>
                ) : null}
              </div>
              <div className="text-center text-sm text-muted-foreground">
                {isLogin ? (
                  <>
                    Sem conta?{" "}
                    <a href="/register" className="underline underline-offset-4">
                      Cadastre-se
                    </a>
                  </>
                ) : isRegister ? (
                  <>
                    Já tem conta?{" "}
                    <a href="/login" className="underline underline-offset-4">
                      Entrar
                    </a>
                  </>
                ) : (
                  <>
                    Lembrou a senha?{" "}
                    <a href="/login" className="underline underline-offset-4">
                      Entrar
                    </a>
                  </>
                )}
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </DirectionProvider>
  );
}

export function mountLoginForm() {
  const node = document.getElementById("auth-root");
  const raw = document.getElementById("auth-props");
  if (!node || !raw?.textContent) {
    return;
  }
  const props = JSON.parse(raw.textContent) as AuthProps;
  createRoot(node).render(<LoginForm {...props} />);
}
