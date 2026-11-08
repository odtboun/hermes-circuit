export function useState(v) { return [typeof v === 'function' ? v() : v, () => {}] }
export function useRef(v) { return { current: v } }
export function useMemo(f) { return f() }
export function useCallback(f) { return f }
export function useEffect() {}
export function useLayoutEffect() {}
