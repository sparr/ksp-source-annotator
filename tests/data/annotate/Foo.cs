using System;

[Serializable]
public class Foo
{
	/// <summary>Old comment to be replaced.</summary>
	public int a, b;

	[NonSerialized]
	public float c;

	public Foo(int x)
	{
	}

	public int this[int i] => i;

	public enum Kind
	{
		One,
		Two
	}

	public void Bar<T>(ref T t, out int n)
	{
		n = 0;
	}

	public int P { get; set; }

	public event Action E;

	/// <summary>Stale: no doc for this one in the XML.</summary>
	public void NoDoc()
	{
	}

	public class Nested
	{
		public void Inner()
		{
		}
	}
}
public delegate void Del(int x);
