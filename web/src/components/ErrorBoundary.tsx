import { Component, type ReactNode } from "react";

/** Keeps one broken panel from blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null; key?: string }> {
  state: { error: Error | null; key?: string } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  static getDerivedStateFromProps(props: { resetKey?: string }, state: { error: Error | null; key?: string }) {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }

  render() {
    if (this.state.error)
      return (
        <div className="p-4 text-sm text-red-800 dark:text-red-200">
          Something went wrong while showing this part: {this.state.error.message}
        </div>
      );
    return this.props.children;
  }
}
