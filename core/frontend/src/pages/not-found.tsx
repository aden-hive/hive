import { useNavigate } from "react-router-dom";

export default function NotFound() {
  const navigate = useNavigate();
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4">
      <h1 className="text-4xl font-bold">404</h1>
      <p className="text-muted-foreground">Page not found</p>
      <button
        onClick={() => navigate("/")}
        className="px-4 py-2 rounded bg-primary text-primary-foreground hover:opacity-90"
      >
        Go home
      </button>
    </div>
  );
}
