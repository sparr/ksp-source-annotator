using System;

/// <summary>
/// A type with a long summary that should certainly need to be wrapped across more than one line
/// because it goes on and on, mentioning <see cref="T:Del" /> and <c>code</c> along the way so that
/// the tag-preserving wrap is exercised too.
/// </summary>
/// <remarks>Source: test.</remarks>
[Serializable]
public class Foo
{
	/// <summary>
	/// Doc for b only, in a two-variable field declaration.
	/// </summary>
	public int a, b;

	/// <summary>
	/// Field with an attribute on its own line.
	/// </summary>
	[NonSerialized]
	public float c;

	/// <summary>
	/// Constructor.
	/// </summary>
	/// <param name="x">The x.</param>
	public Foo(int x)
	{
	}

	/// <summary>
	/// Indexer.
	/// </summary>
	public int this[int i] => i;

	/// <summary>
	/// Nested enum.
	/// </summary>
	public enum Kind
	{
		One,
		/// <summary>
		/// Second value.
		/// </summary>
		Two
	}

	/// <summary>
	/// Generic with ref and out.
	/// </summary>
	/// <typeparam name="T">The T.</typeparam>
	/// <param name="t">The t.</param>
	/// <param name="n">The n.</param>
	public void Bar<T>(ref T t, out int n)
	{
		n = 0;
	}

	/// <summary>
	/// Property.
	/// </summary>
	public int P { get; set; }

	/// <summary>
	/// Event.
	/// </summary>
	public event Action E;

	public void NoDoc()
	{
	}

	public class Nested
	{
		/// <summary>
		/// Nested class method with a code sample.
		/// </summary>
		/// <remarks>
		/// Example: <code>var f = new Foo(1);
		/// f.Bar(ref f, out var n);
		///    if (n &lt; 2) { }</code> and &amp; entities
		/// </remarks>
		public void Inner()
		{
		}
	}
}
/// <summary>
/// Delegate.
/// </summary>
/// <param name="x">The x.</param>
public delegate void Del(int x);
